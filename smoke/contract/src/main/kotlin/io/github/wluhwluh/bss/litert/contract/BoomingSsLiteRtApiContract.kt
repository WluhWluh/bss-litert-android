package io.github.wluhwluh.bss.litert.contract

import com.google.ai.edge.litert.Accelerator
import com.google.ai.edge.litert.CompiledModel
import com.google.ai.edge.litert.Environment
import com.google.ai.edge.litert.TensorBuffer
import com.google.ai.edge.litert.TensorType
import java.io.File

/** Compile-only coverage of the LiteRT API consumed by Booming SS. */
internal fun compileBoomingSsLiteRtApiContract(
    modelFile: File,
    input: FloatArray,
): FloatArray {
    val environment = Environment.create()
    require(environment.getAvailableAccelerators().contains(Accelerator.CPU))

    val cpuOptions = CompiledModel.Options(Accelerator.CPU).apply {
        this.cpuOptions = CompiledModel.CpuOptions(4, 0, null)
    }
    val gpuOptions = CompiledModel.Options(Accelerator.GPU).apply {
        this.gpuOptions = CompiledModel.GpuOptions(
            precision = CompiledModel.GpuOptions.Precision.FP32,
            backend = CompiledModel.GpuOptions.Backend.OPENCL,
            priority = CompiledModel.GpuOptions.Priority.NORMAL,
            numStepsOfCommandBufferPreparations = 4,
        )
    }
    check(gpuOptions.gpuOptions?.backend == CompiledModel.GpuOptions.Backend.OPENCL)

    val model = CompiledModel.create(modelFile.absolutePath, cpuOptions, environment)
    requireStaticFloat(model.getInputTensorType("input"))
    requireStaticFloat(model.getOutputTensorType("output"))
    require(model.getInputBufferRequirements("input").bufferSize > 0)
    require(model.getOutputBufferRequirements("output").bufferSize > 0)

    val inputs: List<TensorBuffer> = model.createInputBuffers()
    val outputs: List<TensorBuffer> = model.createOutputBuffers()
    inputs.single().writeFloat(input)
    model.run(inputs, outputs)
    val result = outputs.single().readFloat()

    outputs.asReversed().forEach(TensorBuffer::close)
    inputs.asReversed().forEach(TensorBuffer::close)
    model.close()
    environment.close()
    return result
}

private fun requireStaticFloat(type: TensorType) {
    require(type.elementType == TensorType.ElementType.FLOAT)
    val layout = requireNotNull(type.layout)
    require(!layout.hasStrides)
    require(layout.dimensions.isNotEmpty())
}
