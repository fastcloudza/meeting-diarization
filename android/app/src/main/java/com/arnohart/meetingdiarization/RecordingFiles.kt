package com.arnohart.meetingdiarization

import android.content.Context
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Where recordings live, and what to do with a file a previous run left behind. */
object RecordingFiles {

    private const val WAV_HEADER_BYTES = 44
    private const val BYTES_PER_SECOND = 8_000 * 2 * 2
    private const val FRAME_BYTES = 4

    /**
     * The folder recordings are written to, or null when the phone's storage
     * is not available. It is private to this app, so no storage permission
     * is needed.
     */
    fun directory(context: Context): File? {
        val base = context.getExternalFilesDir(null) ?: return null
        val dir = File(base, "recordings")
        if (!dir.isDirectory && !dir.mkdirs()) return null
        return dir
    }

    fun secondsOf(file: File): Int =
        ((file.length() - WAV_HEADER_BYTES).coerceAtLeast(0) / BYTES_PER_SECOND).toInt()

    /**
     * If the app was killed while recording, the file still has the
     * placeholder header with both sizes at zero. Many players show such a file
     * as empty. This writes the real sizes from the length of the file.
     * Returns true if it changed anything.
     */
    fun finishInterrupted(file: File): Boolean {
        if (file.length() <= WAV_HEADER_BYTES) return false
        RandomAccessFile(file, "rw").use { f ->
            f.seek(40)
            val raw = ByteArray(4)
            f.readFully(raw)
            val declared = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).int
            if (declared != 0) return false

            // Drop a half written last frame, then patch the two sizes.
            val audioBytes = (file.length() - WAV_HEADER_BYTES) / FRAME_BYTES * FRAME_BYTES
            f.setLength(WAV_HEADER_BYTES + audioBytes)
            f.seek(4)
            f.write(le((WAV_HEADER_BYTES - 8 + audioBytes).toInt()))
            f.seek(40)
            f.write(le(audioBytes.toInt()))
        }
        return true
    }

    /**
     * The newest recording on the phone, made ready to share, as a Saved
     * state. Empty files (a header and nothing else) are removed. Returns null
     * if there is no recording.
     */
    fun recoverLatest(context: Context): RecorderState.Saved? {
        val dir = directory(context) ?: return null
        val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".wav") } ?: return null
        files.filter { it.length() <= WAV_HEADER_BYTES }.forEach { it.delete() }
        val latest = files.filter { it.exists() }.maxByOrNull { it.lastModified() } ?: return null
        val notes = mutableListOf<String>()
        if (finishInterrupted(latest)) {
            notes += "This recording was cut short, probably because the phone stopped the app. " +
                "Its header has been finished so it plays. Everything up to the cut is in the file."
        }
        return RecorderState.Saved(latest, secondsOf(latest), notes)
    }

    private fun le(value: Int): ByteArray =
        ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(value).array()
}

/** What to tell the user about a finished recording, from facts the writer already measures. */
object RecordingNotes {

    private const val SILENT_RMS_TOTAL = 2.0

    fun build(rms: StereoWavWriter.ChannelRms, windowsDropped: Int): List<String> {
        val notes = mutableListOf<String>()
        val total = rms.leftRms + rms.rightRms
        // Real microphone noise sits well above this on a 16 bit scale.
        if (total < SILENT_RMS_TOTAL) {
            notes += "The recording is silent. Another app or a phone call may have been using the microphone."
        } else if (rms.leftRms < total * 0.01 || rms.rightRms < total * 0.01) {
            notes += ("One channel carries under 1%% of the energy of the other " +
                "(left %.1f, right %.1f). This phone may have a single microphone, or one is blocked.")
                .format(rms.leftRms, rms.rightRms)
        }
        if (windowsDropped > 0) {
            notes += "$windowsDropped half second windows of audio were dropped because the writer " +
                "fell behind, so the recording has gaps."
        }
        return notes
    }
}
