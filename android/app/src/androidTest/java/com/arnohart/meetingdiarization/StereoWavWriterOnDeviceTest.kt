package com.arnohart.meetingdiarization

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Instrumented test for the recorder's file format.
 *
 * Runs on a connected device or emulator. Drives [StereoWavWriter] directly,
 * in the device's own JVM and with the real storage path the service uses,
 * which catches device specific format problems that the plain JVM tests miss.
 *
 * Not exercised here: the capture path itself. That needs the microphone
 * permission and a foreground service, so it is checked by making a real
 * recording.
 */
class StereoWavWriterOnDeviceTest {

    @Test
    fun stereo_wav_writer_produces_valid_8khz_stereo_pcm_on_device() {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = File(ctx.getExternalFilesDir(null), "recordings_test").apply { mkdirs() }
        val out = File(dir, "smoke_test.wav").apply { delete() }

        val w = StereoWavWriter(out.absolutePath).apply { open() }
        // Three 500 ms stereo windows are 1.5 s of audio at the 8 kHz output rate.
        repeat(3) {
            w.writeStereoWindow(
                ShortArray(8000) { (it % 5000).toShort() },
                ShortArray(8000) { ((it + 1234) % 5000).toShort() },
            )
        }
        w.close()

        assertTrue("output file must exist", out.exists())
        val bytes = out.readBytes()

        assertEquals("RIFF", String(bytes, 0, 4, Charsets.US_ASCII))
        assertEquals("WAVE", String(bytes, 8, 4, Charsets.US_ASCII))
        val channels = ByteBuffer.wrap(bytes, 22, 2).order(ByteOrder.LITTLE_ENDIAN).short
        assertEquals(2, channels.toInt())
        val sampleRate = ByteBuffer.wrap(bytes, 24, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(8000, sampleRate)
        val bitsPerSample = ByteBuffer.wrap(bytes, 34, 2).order(ByteOrder.LITTLE_ENDIAN).short
        assertEquals(16, bitsPerSample.toInt())

        // 3 windows * 4000 frames * 2 channels * 2 bytes = 48_000
        val dataSize = ByteBuffer.wrap(bytes, 40, 4).order(ByteOrder.LITTLE_ENDIAN).int
        assertEquals(48_000, dataSize)
        assertEquals(44 + 48_000, bytes.size)

        out.delete()
    }
}
