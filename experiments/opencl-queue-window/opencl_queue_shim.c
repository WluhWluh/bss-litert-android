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
#include <stdbool.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/system_properties.h>
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
  BSS_MAX_TRACKED_QUEUES = 32,
  BSS_MIN_WINDOW_SIZE = 1,
  BSS_MAX_WINDOW_SIZE = 1024,
};

static const char *const kLogTag = "BssOpenClQueueShim";
static const char *const kWindowProperty =
    "debug.bss.opencl_queue_window";

struct queue_counter {
  cl_command_queue queue;
  uint64_t dispatches;
};

static pthread_once_t g_init_once = PTHREAD_ONCE_INIT;
static pthread_mutex_t g_queue_mutex = PTHREAD_MUTEX_INITIALIZER;
static struct queue_counter g_queue_counters[BSS_MAX_TRACKED_QUEUES];
static enqueue_nd_range_kernel_fn g_real_enqueue;
static wait_for_events_fn g_real_wait;
static release_event_fn g_real_release;
static int g_window_size;
static _Atomic bool g_inference_enabled;
static _Atomic uint64_t g_dispatch_count;
static _Atomic uint64_t g_wait_count;
static _Atomic uint64_t g_total_wait_ns;
static _Atomic uint64_t g_max_wait_ns;

static void *resolve_vendor_symbol(const char *name) {
  void *symbol = dlsym(RTLD_NEXT, name);
  if (symbol == NULL) {
    __android_log_print(ANDROID_LOG_ERROR, kLogTag,
                        "Could not resolve vendor symbol %s: %s", name,
                        dlerror());
  }
  return symbol;
}

static int read_window_size(void) {
  char value[PROP_VALUE_MAX] = {0};
  if (__system_property_get(kWindowProperty, value) <= 0) {
    return 0;
  }

  char *end = NULL;
  const long parsed = strtol(value, &end, 10);
  if (end == value || *end != '\0' || parsed < BSS_MIN_WINDOW_SIZE ||
      parsed > BSS_MAX_WINDOW_SIZE) {
    return 0;
  }
  return (int)parsed;
}

static void initialize_shim(void) {
  g_window_size = read_window_size();
  g_real_enqueue =
      (enqueue_nd_range_kernel_fn)resolve_vendor_symbol(
          "clEnqueueNDRangeKernel");
  g_real_wait =
      (wait_for_events_fn)resolve_vendor_symbol("clWaitForEvents");
  g_real_release =
      (release_event_fn)resolve_vendor_symbol("clReleaseEvent");
  __android_log_print(ANDROID_LOG_INFO, kLogTag,
                      "Initialized with queue window %d", g_window_size);
}

static int should_wait_after_dispatch(cl_command_queue queue) {
  if (g_window_size == 0 ||
      !atomic_load_explicit(&g_inference_enabled, memory_order_relaxed)) {
    return 0;
  }
  atomic_fetch_add_explicit(&g_dispatch_count, 1, memory_order_relaxed);

  uint64_t dispatches = 0;
  pthread_mutex_lock(&g_queue_mutex);
  struct queue_counter *empty = NULL;
  struct queue_counter *selected = NULL;
  for (size_t i = 0; i < BSS_MAX_TRACKED_QUEUES; ++i) {
    if (g_queue_counters[i].queue == queue) {
      selected = &g_queue_counters[i];
      break;
    }
    if (empty == NULL && g_queue_counters[i].queue == NULL) {
      empty = &g_queue_counters[i];
    }
  }
  if (selected == NULL) {
    selected = empty != NULL ? empty : &g_queue_counters[0];
    selected->queue = queue;
    selected->dispatches = 0;
  }
  dispatches = ++selected->dispatches;
  pthread_mutex_unlock(&g_queue_mutex);

  return dispatches % (uint64_t)g_window_size == 0;
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
  const uint64_t wait_count =
      atomic_fetch_add_explicit(&g_wait_count, 1, memory_order_relaxed) + 1;
  atomic_fetch_add_explicit(&g_total_wait_ns, duration_ns,
                            memory_order_relaxed);

  uint64_t previous_max =
      atomic_load_explicit(&g_max_wait_ns, memory_order_relaxed);
  while (duration_ns > previous_max &&
         !atomic_compare_exchange_weak_explicit(
             &g_max_wait_ns, &previous_max, duration_ns,
             memory_order_relaxed, memory_order_relaxed)) {
  }

  if (wait_count == 1 || wait_count % 256 == 0) {
    const uint64_t total_ns =
        atomic_load_explicit(&g_total_wait_ns, memory_order_relaxed);
    const uint64_t maximum_ns =
        atomic_load_explicit(&g_max_wait_ns, memory_order_relaxed);
    __android_log_print(
        ANDROID_LOG_INFO, kLogTag,
        "Bounded waits=%llu mean=%.3fms max=%.3fms window=%d",
        (unsigned long long)wait_count,
        (double)total_ns / (double)wait_count / 1000000.0,
        (double)maximum_ns / 1000000.0, g_window_size);
  }
}

__attribute__((visibility("default"))) cl_int clEnqueueNDRangeKernel(
    cl_command_queue command_queue, cl_kernel kernel, cl_uint work_dim,
    const size_t *global_work_offset, const size_t *global_work_size,
    const size_t *local_work_size, cl_uint num_events_in_wait_list,
    const cl_event *event_wait_list, cl_event *event) {
  pthread_once(&g_init_once, initialize_shim);
  if (g_real_enqueue == NULL) {
    return -59; /* CL_INVALID_OPERATION */
  }

  const int wait_after_dispatch = should_wait_after_dispatch(command_queue);
  cl_event boundary_event = NULL;
  cl_event *result_event =
      wait_after_dispatch && event == NULL ? &boundary_event : event;
  const cl_int enqueue_status = g_real_enqueue(
      command_queue, kernel, work_dim, global_work_offset, global_work_size,
      local_work_size, num_events_in_wait_list, event_wait_list, result_event);
  if (enqueue_status != CL_SUCCESS || !wait_after_dispatch) {
    return enqueue_status;
  }
  if (g_real_wait == NULL || g_real_release == NULL) {
    return -59; /* CL_INVALID_OPERATION */
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
      "window=%d",
      (unsigned long long)dispatch_count, (unsigned long long)wait_count,
      mean_ms, (double)maximum_ns / 1000000.0, g_window_size);
}

__attribute__((visibility("default"))) JNIEXPORT void JNICALL
Java_com_mardous_booming_separation_model_litert_MdxLiteRtOpenClQueueExperiment_nativeReset(
    JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  pthread_once(&g_init_once, initialize_shim);
  atomic_store_explicit(&g_inference_enabled, false, memory_order_relaxed);
  atomic_store_explicit(&g_dispatch_count, 0, memory_order_relaxed);
  atomic_store_explicit(&g_wait_count, 0, memory_order_relaxed);
  atomic_store_explicit(&g_total_wait_ns, 0, memory_order_relaxed);
  atomic_store_explicit(&g_max_wait_ns, 0, memory_order_relaxed);
  pthread_mutex_lock(&g_queue_mutex);
  for (size_t i = 0; i < BSS_MAX_TRACKED_QUEUES; ++i) {
    g_queue_counters[i].queue = NULL;
    g_queue_counters[i].dispatches = 0;
  }
  pthread_mutex_unlock(&g_queue_mutex);
  __android_log_print(ANDROID_LOG_INFO, kLogTag,
                      "Reset inference counters for queue window %d",
                      g_window_size);
}

__attribute__((visibility("default"))) JNIEXPORT jint JNICALL
Java_com_mardous_booming_separation_model_litert_MdxLiteRtOpenClQueueExperiment_nativeGetQueueWindow(
    JNIEnv *env, jclass clazz) {
  (void)env;
  (void)clazz;
  pthread_once(&g_init_once, initialize_shim);
  return (jint)g_window_size;
}

__attribute__((visibility("default"))) JNIEXPORT void JNICALL
Java_com_mardous_booming_separation_model_litert_MdxLiteRtOpenClQueueExperiment_nativeSetInferenceEnabled(
    JNIEnv *env, jclass clazz, jboolean enabled) {
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
