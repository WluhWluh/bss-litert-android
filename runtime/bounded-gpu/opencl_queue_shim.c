/*
 * Copyright 2026 Booming SS contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#define _GNU_SOURCE

#include <android/log.h>
#include <dlfcn.h>
#include <jni.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

typedef int32_t cl_int;
typedef uint32_t cl_uint;
typedef struct _cl_command_queue *cl_command_queue;
typedef struct _cl_kernel *cl_kernel;
typedef struct _cl_event *cl_event;

typedef cl_int (*enqueue_nd_range_kernel_fn)(
    cl_command_queue command_queue, cl_kernel kernel, cl_uint work_dim,
    const size_t *global_work_offset, const size_t *global_work_size,
    const size_t *local_work_size, cl_uint num_events_in_wait_list,
    const cl_event *event_wait_list, cl_event *event);
typedef cl_int (*wait_for_events_fn)(cl_uint num_events,
                                     const cl_event *event_list);
typedef cl_int (*release_event_fn)(cl_event event);

enum {
  CL_SUCCESS = 0,
  CL_INVALID_OPERATION = -59,
  BSS_CAPABILITY_SCHEMA_VERSION = 1,
  BSS_KERNEL_BATCH_SIZE = 1,
  BSS_COMMAND_QUEUE_WINDOW_SIZE = 1,
};

static const char *const kLogTag = "BssBoundedOpenCl";
static const char *const kArtifactVersion = "2.1.5-bss.2";
static const char *const kProfileId = "gpu-opencl-bounded-fp32-v1";

static pthread_once_t g_init_once = PTHREAD_ONCE_INIT;
static _Atomic bool g_inference_enabled;
static _Atomic uint64_t g_dispatch_count;
static _Atomic uint64_t g_wait_count;
static _Atomic uint64_t g_total_wait_ns;
static _Atomic uint64_t g_max_wait_ns;
static enqueue_nd_range_kernel_fn g_real_enqueue;
static wait_for_events_fn g_real_wait;
static release_event_fn g_real_release;

static void *resolve_vendor_symbol(const char *name) {
  void *symbol = dlsym(RTLD_NEXT, name);
  if (symbol == NULL) {
    __android_log_print(ANDROID_LOG_ERROR, kLogTag,
                        "Could not resolve vendor symbol %s: %s", name,
                        dlerror());
  }
  return symbol;
}

static void initialize_shim(void) {
  g_real_enqueue = (enqueue_nd_range_kernel_fn)resolve_vendor_symbol(
      "clEnqueueNDRangeKernel");
  g_real_wait =
      (wait_for_events_fn)resolve_vendor_symbol("clWaitForEvents");
  g_real_release =
      (release_event_fn)resolve_vendor_symbol("clReleaseEvent");
  __android_log_print(ANDROID_LOG_INFO, kLogTag,
                      "Initialized fixed bounded queue profile %s",
                      kProfileId);
}

static uint64_t monotonic_time_ns(void) {
  struct timespec now;
  if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
    return 0;
  }
  return (uint64_t)now.tv_sec * UINT64_C(1000000000) +
         (uint64_t)now.tv_nsec;
}

static void record_wait(uint64_t duration_ns) {
  atomic_fetch_add_explicit(&g_wait_count, 1, memory_order_relaxed);
  atomic_fetch_add_explicit(&g_total_wait_ns, duration_ns,
                            memory_order_relaxed);
  uint64_t previous_max =
      atomic_load_explicit(&g_max_wait_ns, memory_order_relaxed);
  while (duration_ns > previous_max &&
         !atomic_compare_exchange_weak_explicit(
             &g_max_wait_ns, &previous_max, duration_ns,
             memory_order_relaxed, memory_order_relaxed)) {
  }
}

__attribute__((visibility("default"))) cl_int clEnqueueNDRangeKernel(
    cl_command_queue command_queue, cl_kernel kernel, cl_uint work_dim,
    const size_t *global_work_offset, const size_t *global_work_size,
    const size_t *local_work_size, cl_uint num_events_in_wait_list,
  const cl_event *event_wait_list, cl_event *event) {
  pthread_once(&g_init_once, initialize_shim);
  if (g_real_enqueue == NULL) {
    return CL_INVALID_OPERATION;
  }

  const bool should_wait = atomic_load_explicit(
      &g_inference_enabled, memory_order_relaxed);
  if (should_wait) {
    atomic_fetch_add_explicit(&g_dispatch_count, 1, memory_order_relaxed);
  }
  cl_event boundary_event = NULL;
  cl_event *result_event = should_wait && event == NULL ? &boundary_event : event;
  const cl_int enqueue_status = g_real_enqueue(
      command_queue, kernel, work_dim, global_work_offset, global_work_size,
      local_work_size, num_events_in_wait_list, event_wait_list, result_event);
  if (enqueue_status != CL_SUCCESS || !should_wait) {
    return enqueue_status;
  }
  if (g_real_wait == NULL || g_real_release == NULL) {
    return CL_INVALID_OPERATION;
  }

  const cl_event event_to_wait = event == NULL ? boundary_event : *event;
  const uint64_t started_ns = monotonic_time_ns();
  const cl_int wait_status = g_real_wait(1, &event_to_wait);
  const uint64_t ended_ns = monotonic_time_ns();
  if (ended_ns >= started_ns) {
    record_wait(ended_ns - started_ns);
  }

  if (event == NULL && boundary_event != NULL) {
    const cl_int release_status = g_real_release(boundary_event);
    if (wait_status == CL_SUCCESS && release_status != CL_SUCCESS) {
      return release_status;
    }
  }
  return wait_status;
}

static void reset_counters(void) {
  atomic_store_explicit(&g_inference_enabled, false, memory_order_relaxed);
  atomic_store_explicit(&g_dispatch_count, 0, memory_order_relaxed);
  atomic_store_explicit(&g_wait_count, 0, memory_order_relaxed);
  atomic_store_explicit(&g_total_wait_ns, 0, memory_order_relaxed);
  atomic_store_explicit(&g_max_wait_ns, 0, memory_order_relaxed);
}

static void log_summary(void) {
  const uint64_t dispatch_count =
      atomic_load_explicit(&g_dispatch_count, memory_order_relaxed);
  const uint64_t wait_count =
      atomic_load_explicit(&g_wait_count, memory_order_relaxed);
  const uint64_t total_ns =
      atomic_load_explicit(&g_total_wait_ns, memory_order_relaxed);
  const uint64_t maximum_ns =
      atomic_load_explicit(&g_max_wait_ns, memory_order_relaxed);
  const double mean_ms = wait_count == 0
                             ? 0.0
                             : (double)total_ns / (double)wait_count / 1000000.0;
  __android_log_print(
      ANDROID_LOG_INFO, kLogTag,
      "Inference summary dispatches=%llu waits=%llu mean=%.3fms max=%.3fms "
      "kernelBatch=1 queueWindow=1",
      (unsigned long long)dispatch_count, (unsigned long long)wait_count,
      mean_ms, (double)maximum_ns / 1000000.0);
}

#define BSS_JNI(name) \
  Java_io_github_wluhwluh_bss_litert_BssLiteRtRuntime_##name

__attribute__((visibility("default"))) JNIEXPORT jint JNICALL
BSS_JNI(nativeGetCapabilitySchemaVersion)(JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  return BSS_CAPABILITY_SCHEMA_VERSION;
}

__attribute__((visibility("default"))) JNIEXPORT jstring JNICALL
BSS_JNI(nativeGetArtifactVersion)(JNIEnv *env, jclass clazz) {
  (void)clazz;
  return (*env)->NewStringUTF(env, kArtifactVersion);
}

__attribute__((visibility("default"))) JNIEXPORT jstring JNICALL
BSS_JNI(nativeGetProfileId)(JNIEnv *env, jclass clazz) {
  (void)clazz;
  return (*env)->NewStringUTF(env, kProfileId);
}

__attribute__((visibility("default"))) JNIEXPORT jint JNICALL
BSS_JNI(nativeGetKernelBatchSize)(JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  return BSS_KERNEL_BATCH_SIZE;
}

__attribute__((visibility("default"))) JNIEXPORT jint JNICALL
BSS_JNI(nativeGetCommandQueueWindowSize)(JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  return BSS_COMMAND_QUEUE_WINDOW_SIZE;
}

__attribute__((visibility("default"))) JNIEXPORT void JNICALL
BSS_JNI(nativeResetInferenceCounters)(JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  pthread_once(&g_init_once, initialize_shim);
  reset_counters();
}

__attribute__((visibility("default"))) JNIEXPORT void JNICALL
BSS_JNI(nativeSetInferenceEnabled)(JNIEnv *env, jclass clazz,
                                   jboolean enabled) {
  (void)env;
  (void)clazz;
  pthread_once(&g_init_once, initialize_shim);
  const bool requested = enabled == JNI_TRUE;
  const bool previous = atomic_exchange_explicit(
      &g_inference_enabled, requested, memory_order_relaxed);
  if (previous && !requested) {
    log_summary();
  }
}

__attribute__((visibility("default"))) JNIEXPORT jlong JNICALL
BSS_JNI(nativeGetDispatchCount)(JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  return (jlong)atomic_load_explicit(&g_dispatch_count,
                                     memory_order_relaxed);
}

__attribute__((visibility("default"))) JNIEXPORT jlong JNICALL
BSS_JNI(nativeGetEventWaitCount)(JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  return (jlong)atomic_load_explicit(&g_wait_count, memory_order_relaxed);
}
