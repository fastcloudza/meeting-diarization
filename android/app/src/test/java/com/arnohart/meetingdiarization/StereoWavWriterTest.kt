package com.arnohart.meetingdiarization

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Locks in the WAV format that comes off the phone.
 *
 * Pure JVM: [StereoWavWriter] needs nothing from Android. This catches drift
 * in the output format: sample rate, channel count, bit depth, header size and
 * data chunk size. The recording is the recorder's only product, so this test
 * is the gate on it.
 */
class StereoWavWriterTest {

    @Test
    fun writes_correct_stereo_wav_header_and_data_size() {
        val tmp = File.createTempFile("stereo_wav_test", ".wav").apply { deleteOnExit() }
        val w = StereoWavWriter(tmp.absolutePath).apply { open() }

        // 500 ms of 16 kHz audio per channel, as deterministic ramps.
        val left = ShortArray(8000) { (it % 1000).toShort() }
        val right = ShortArray(8000) { ((it * 2) % 1000).toShort() }
        w.writeStereoWindow(left, right)
        w.close()

        val bytes = tmp.readBytes()

        // RIFF / WAVE / fmt header.
        assertEquals("RIFF", String(bytes, 0, 4, Charsets.US_ASCII))
        assertEquals("WAVE", String(bytes, 8, 4, Charsets.US_ASCII))
        assertEquals("fmt ", String(bytes, 12, 4, Charsets.US_ASCII))

        val fmtSize = leInt(bytes, 16)
        assertEquals(16, fmtSize)

        val pcmFormat = leShort(bytes, 20)
        assertEquals(1, pcmFormat.toInt())            // PCM = 1

        val channels = leShort(bytes, 22)
        assertEquals(2, channels.toInt())             // stereo

        val sampleRate = leInt(bytes, 24)
        assertEquals(8000, sampleRate)                // 8 kHz output

        val byteRate = leInt(bytes, 28)
        // 8000 Hz * 2 channels * 2 bytes per sample = 32_000
        assertEquals(32_000, byteRate)

        val blockAlign = leShort(bytes, 32)
        // 2 channels * 2 bytes per sample = 4
        assertEquals(4, blockAlign.toInt())

        val bitsPerSample = leShort(bytes, 34)
        assertEquals(16, bitsPerSample.toInt())

        // Data chunk.
        assertEquals("data", String(bytes, 36, 4, Charsets.US_ASCII))
        val dataSize = leInt(bytes, 40)
        // Input was 8000 frames @ 16 kHz; decimated 2 to 1 to 4000 frames
        // @ 8 kHz; stereo and 16 bit = 4000 * 2 * 2 = 16_000 bytes.
        assertEquals(16_000, dataSize)

        // Total file = 44 byte header + data chunk.
        assertEquals(44 + 16_000, bytes.size)
    }

    @Test
    fun writes_silence_correctly_without_crashing() {
        val tmp = File.createTempFile("stereo_wav_silence", ".wav").apply { deleteOnExit() }
        val w = StereoWavWriter(tmp.absolutePath).apply { open() }
        w.writeStereoWindow(ShortArray(8000), ShortArray(8000))
        w.close()
        // 8000 input frames give 4000 output frames, so 16_000 data bytes
        assertEquals(44 + 16_000, tmp.length().toInt())
    }

    @Test
    fun close_patches_riff_and_data_sizes_correctly_for_two_windows() {
        val tmp = File.createTempFile("stereo_wav_two", ".wav").apply { deleteOnExit() }
        val w = StereoWavWriter(tmp.absolutePath).apply { open() }
        w.writeStereoWindow(ShortArray(8000) { 100 }, ShortArray(8000) { 200 })
        w.writeStereoWindow(ShortArray(8000) { 300 }, ShortArray(8000) { 400 })
        w.close()

        val bytes = tmp.readBytes()
        // Two windows give 8000 frames @ 8 kHz, so 32_000 bytes of data.
        val dataSize = leInt(bytes, 40)
        assertEquals(32_000, dataSize)

        // RIFF size is "everything after the first 8 bytes" = the file size minus 8.
        val riffSize = leInt(bytes, 4)
        assertEquals(bytes.size - 8, riffSize)
    }

    private fun leInt(arr: ByteArray, off: Int): Int =
        ByteBuffer.wrap(arr, off, 4).order(ByteOrder.LITTLE_ENDIAN).int

    private fun leShort(arr: ByteArray, off: Int): Short =
        ByteBuffer.wrap(arr, off, 2).order(ByteOrder.LITTLE_ENDIAN).short
}
