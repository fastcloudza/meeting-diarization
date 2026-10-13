package com.arnohart.meetingdiarization

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * What the app does with a recording that was cut short, and what it tells
 * the user about a finished one. Pure JVM.
 */
class RecordingFilesTest {

    /** A file as the writer leaves it if the app is killed: header sizes at zero. */
    private fun interruptedFile(audioBytes: Int): File {
        val tmp = File.createTempFile("interrupted", ".wav").apply { deleteOnExit() }
        val w = StereoWavWriter(tmp.absolutePath).apply { open() }
        // One window is 4000 frames at 8 kHz, which is 16_000 bytes.
        repeat(audioBytes / 16_000) { w.writeStereoWindow(ShortArray(8000) { 7 }, ShortArray(8000) { 9 }) }
        // Not closed, so the sizes in the header stay at zero.
        return tmp
    }

    private fun leInt(arr: ByteArray, off: Int): Int =
        ByteBuffer.wrap(arr, off, 4).order(ByteOrder.LITTLE_ENDIAN).int

    @Test
    fun finishes_the_header_of_a_file_that_was_never_closed() {
        val f = interruptedFile(32_000)
        assertEquals(0, leInt(f.readBytes(), 40))

        assertTrue(RecordingFiles.finishInterrupted(f))

        val bytes = f.readBytes()
        assertEquals(32_000, leInt(bytes, 40))
        assertEquals(bytes.size - 8, leInt(bytes, 4))
        assertEquals(1, RecordingFiles.secondsOf(f))
    }

    @Test
    fun drops_a_half_written_last_frame() {
        val f = interruptedFile(16_000)
        f.appendBytes(byteArrayOf(1, 2, 3))   // three stray bytes, less than one 4 byte frame

        assertTrue(RecordingFiles.finishInterrupted(f))

        assertEquals(44 + 16_000, f.length().toInt())
        assertEquals(16_000, leInt(f.readBytes(), 40))
    }

    @Test
    fun leaves_a_properly_closed_file_alone() {
        val tmp = File.createTempFile("closed", ".wav").apply { deleteOnExit() }
        val w = StereoWavWriter(tmp.absolutePath).apply { open() }
        w.writeStereoWindow(ShortArray(8000), ShortArray(8000))
        w.close()
        val before = tmp.readBytes()

        assertFalse(RecordingFiles.finishInterrupted(tmp))

        assertEquals(before.toList(), tmp.readBytes().toList())
    }

    @Test
    fun a_header_with_no_audio_is_not_a_recording() {
        val f = interruptedFile(0)
        assertFalse(RecordingFiles.finishInterrupted(f))
    }

    @Test
    fun says_nothing_about_a_healthy_recording() {
        val notes = RecordingNotes.build(StereoWavWriter.ChannelRms(500.0, 450.0), 0)
        assertTrue(notes.isEmpty())
    }

    @Test
    fun says_when_the_recording_is_silent() {
        val notes = RecordingNotes.build(StereoWavWriter.ChannelRms(0.0, 0.0), 0)
        assertEquals(1, notes.size)
        assertTrue(notes[0].contains("silent"))
    }

    @Test
    fun says_when_the_recording_is_only_a_trace_of_noise() {
        val notes = RecordingNotes.build(StereoWavWriter.ChannelRms(0.4, 0.4), 0)
        assertEquals(1, notes.size)
        assertTrue(notes[0].contains("silent"))
    }

    @Test
    fun says_when_one_channel_is_almost_empty() {
        val notes = RecordingNotes.build(StereoWavWriter.ChannelRms(800.0, 2.0), 0)
        assertEquals(1, notes.size)
        assertTrue(notes[0].contains("single microphone"))
    }

    @Test
    fun says_when_windows_were_dropped() {
        val notes = RecordingNotes.build(StereoWavWriter.ChannelRms(500.0, 450.0), 3)
        assertEquals(1, notes.size)
        assertTrue(notes[0].startsWith("3 half second windows"))
    }
}
