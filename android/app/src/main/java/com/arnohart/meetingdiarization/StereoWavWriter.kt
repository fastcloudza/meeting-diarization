package com.arnohart.meetingdiarization

import android.util.Log
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * StereoWavWriter writes the stereo WAV file of a meeting capture.
 *
 * Output format:
 *   * 8 kHz sample rate
 *   * 16 bit signed PCM
 *   * Stereo (2 channels)
 *   * L and R carry the raw two microphone capture. The channels are not
 *     attributed to speakers. Who spoke when is worked out afterwards, on the
 *     server, from the recording alone.
 *
 * The writer takes windows at 16 kHz and reduces them to 8 kHz by a simple
 * 2 to 1 decimation that averages each pair of samples.
 *
 * Threading: the writer is not thread safe. Funnel all [writeStereoWindow]
 * calls through a single thread (the writer thread in
 * [DiarisedRecordingService]).
 */
class StereoWavWriter(
    private val outputPath: String,
) {

    companion object {
        private const val TAG = "MeetingRecorder.StereoWav"
        private const val OUTPUT_SAMPLE_RATE = 8_000
        private const val INPUT_SAMPLE_RATE = 16_000
        private const val BYTES_PER_SAMPLE = 2
        private const val CHANNELS = 2
        private const val WAV_HEADER_BYTES = 44
    }

    private var file: RandomAccessFile? = null
    private var samplesWrittenPerChannel: Int = 0

    // Per channel energy accumulators, read through channelRms() after close()
    // for channel content diagnostics.
    private var leftSumSq: Double = 0.0
    private var leftSamples: Int = 0
    private var rightSumSq: Double = 0.0
    private var rightSamples: Int = 0

    /** Final per channel RMS over all samples written. */
    data class ChannelRms(val leftRms: Double, val rightRms: Double)

    fun channelRms(): ChannelRms {
        val l = if (leftSamples > 0) Math.sqrt(leftSumSq / leftSamples) else 0.0
        val r = if (rightSamples > 0) Math.sqrt(rightSumSq / rightSamples) else 0.0
        return ChannelRms(l, r)
    }

    /** Frames written so far on each channel, at the 8 kHz output rate. */
    fun framesWritten(): Int = samplesWrittenPerChannel

    /**
     * Open the file and write a placeholder header. The header is patched
     * with the real sizes when [close] is called.
     */
    fun open() {
        val f = RandomAccessFile(outputPath, "rw")
        f.setLength(0)
        f.write(buildPlaceholderHeader())
        file = f
        samplesWrittenPerChannel = 0
        leftSumSq = 0.0
        leftSamples = 0
        rightSumSq = 0.0
        rightSamples = 0
        Log.i(TAG, "Opened stereo WAV for write: $outputPath")
    }

    /**
     * Write one 500 ms stereo window: left and right captured from the
     * device's two microphones.
     *
     * Both inputs are at 16 kHz and the same length. Each is decimated 2 to 1
     * to 8 kHz and written to the matching channel of the output file. The RMS
     * counters update for both channels on every window.
     */
    fun writeStereoWindow(left16kHz: ShortArray, right16kHz: ShortArray) {
        val f = file ?: run {
            Log.w(TAG, "writeStereoWindow called before open(); ignoring")
            return
        }
        require(left16kHz.size == right16kHz.size) {
            "writeStereoWindow: L (${left16kHz.size}) and R (${right16kHz.size}) length mismatch"
        }

        val leftDecimated = decimate2to1(left16kHz)
        val rightDecimated = decimate2to1(right16kHz)
        val frameCount = leftDecimated.size

        val byteBuffer = ByteBuffer
            .allocate(frameCount * CHANNELS * BYTES_PER_SAMPLE)
            .order(ByteOrder.LITTLE_ENDIAN)

        var leftSumSqLocal = 0.0
        var rightSumSqLocal = 0.0
        for (i in 0 until frameCount) {
            val l = leftDecimated[i]
            val r = rightDecimated[i]
            byteBuffer.putShort(l)   // L
            byteBuffer.putShort(r)   // R
            val ld = l.toDouble()
            val rd = r.toDouble()
            leftSumSqLocal += ld * ld
            rightSumSqLocal += rd * rd
        }

        f.write(byteBuffer.array())
        samplesWrittenPerChannel += frameCount

        // Both channels carry real audio, so credit both to the RMS.
        leftSumSq += leftSumSqLocal
        leftSamples += frameCount
        rightSumSq += rightSumSqLocal
        rightSamples += frameCount
    }

    /**
     * Patch the header with the final sizes and close the file.
     * A failure to patch the header is thrown to the caller, after the file
     * has been closed.
     */
    fun close() {
        val f = file ?: return
        try {
            val dataBytes = samplesWrittenPerChannel * CHANNELS * BYTES_PER_SAMPLE
            val riffSize = WAV_HEADER_BYTES - 8 + dataBytes
            f.seek(4)
            f.write(
                ByteBuffer
                    .allocate(4)
                    .order(ByteOrder.LITTLE_ENDIAN)
                    .putInt(riffSize)
                    .array()
            )
            f.seek(40)
            f.write(
                ByteBuffer
                    .allocate(4)
                    .order(ByteOrder.LITTLE_ENDIAN)
                    .putInt(dataBytes)
                    .array()
            )
            Log.i(TAG, "Closed stereo WAV: samples/ch=$samplesWrittenPerChannel bytes=$dataBytes")
        } finally {
            try { f.close() } catch (_: Exception) {}
            file = null
        }
    }

    /**
     * Simple 2 to 1 decimation. Each output sample is the average of two
     * input samples. That acts as a crude low pass filter, adequate for
     * speech. A proper half band filter could replace it.
     */
    private fun decimate2to1(input: ShortArray): ShortArray {
        val outLen = input.size / 2
        val out = ShortArray(outLen)
        var i = 0
        var j = 0
        while (j < outLen) {
            val a = input[i].toInt()
            val b = input[i + 1].toInt()
            out[j] = ((a + b) / 2).toShort()
            i += 2
            j += 1
        }
        return out
    }

    /**
     * Build a 44 byte WAV header with placeholder sizes (patched on close).
     */
    private fun buildPlaceholderHeader(): ByteArray {
        val buf = ByteBuffer.allocate(WAV_HEADER_BYTES).order(ByteOrder.LITTLE_ENDIAN)
        val byteRate = OUTPUT_SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE
        val blockAlign = CHANNELS * BYTES_PER_SAMPLE

        buf.put("RIFF".toByteArray(Charsets.US_ASCII))
        buf.putInt(0)                              // RIFF size (patched on close)
        buf.put("WAVE".toByteArray(Charsets.US_ASCII))
        buf.put("fmt ".toByteArray(Charsets.US_ASCII))
        buf.putInt(16)                             // fmt chunk size
        buf.putShort(1)                            // PCM format
        buf.putShort(CHANNELS.toShort())
        buf.putInt(OUTPUT_SAMPLE_RATE)
        buf.putInt(byteRate)
        buf.putShort(blockAlign.toShort())
        buf.putShort((BYTES_PER_SAMPLE * 8).toShort())    // bits per sample
        buf.put("data".toByteArray(Charsets.US_ASCII))
        buf.putInt(0)                              // data size (patched on close)

        return buf.array()
    }
}
