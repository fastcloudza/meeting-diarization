package com.arnohart.meetingdiarization

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * DiarisedRecordingService is the meeting recorder.
 *
 * The device captures stereo and saves it as it is. Speaker separation is not
 * done on the phone. It is done afterwards, on the server, from the recording
 * alone, which is what the server folder of this repository does.
 *
 * Flow:
 *
 *   1. The user taps Start, and ACTION_START arrives.
 *   2. The foreground notification appears. That is what keeps the service
 *      recording with the screen off.
 *   3. The capture thread reads 16 kHz stereo PCM in 500 ms windows from
 *      AudioSource.CAMCORDER with CHANNEL_IN_STEREO. Each window is
 *      interleaved L/R (WINDOW_FRAMES * 2 shorts) and goes onto a bounded
 *      queue.
 *   4. The writer thread drains the queue, deinterleaves each window and
 *      writes it with [StereoWavWriter.writeStereoWindow]. Both microphones'
 *      raw audio reaches the file. The channels are not attributed to
 *      speakers.
 *   5. The user taps Stop, and ACTION_STOP arrives. Both threads drain, the
 *      WAV is closed with a patched header, and the result is published
 *      through [RecorderStatus].
 *
 * Output file:
 *
 *   {external files dir}/recordings/{uuid}_{yyyyMMdd_HHmmss}.wav
 *   (stereo, 8 kHz, 16 bit PCM)
 *
 * Every way a recording can fail to start, or end early, is reported through
 * [RecorderStatus] with a message, and the notification is removed.
 */
class DiarisedRecordingService : Service() {

    companion object {
        private const val TAG = "MeetingRecorder.DiarRec"
        const val ACTION_START = "com.arnohart.meetingdiarization.START_DIARISED_RECORDING"
        const val ACTION_STOP = "com.arnohart.meetingdiarization.STOP_DIARISED_RECORDING"

        private const val NOTIFICATION_CHANNEL_ID = "meeting_recorder"
        private const val NOTIFICATION_ID = 1337

        private const val CAPTURE_SAMPLE_RATE = 16_000
        private const val WINDOW_MS = 500
        // Frames per channel per window: 8000 at 16 kHz and 500 ms.
        private const val WINDOW_FRAMES = CAPTURE_SAMPLE_RATE * WINDOW_MS / 1000
        // Total shorts per window with interleaved stereo (L,R,L,R,...)
        private const val WINDOW_SHORTS_STEREO = WINDOW_FRAMES * 2

        // Queue capacity: 20 windows is 10 seconds of audio buffered
        private const val QUEUE_CAPACITY = 20

        // Reads that return no audio, in a row, before the recording is abandoned.
        private const val MAX_EMPTY_READS = 100
    }

    /** True while the capture and writer threads should keep going. */
    private val running = AtomicBoolean(false)

    /** True from the moment a recording starts until it has been finished once. */
    private val active = AtomicBoolean(false)

    /** The first reason a running recording had to end early, if any. */
    private val failure = AtomicReference<String?>(null)

    private val mainHandler = Handler(Looper.getMainLooper())

    private var captureThread: Thread? = null
    private var consumerThread: Thread? = null
    private var audioRecord: AudioRecord? = null

    private var wavWriter: StereoWavWriter? = null

    private var callUuid: String = ""
    private var wavPath: String = ""
    private var startedAtMs: Long = 0

    @Volatile private var windowsProcessed: Int = 0
    @Volatile private var windowsDropped: Int = 0

    private val windowQueue = LinkedBlockingQueue<ShortArray>(QUEUE_CAPACITY)

    // Service lifecycle
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startRecording()
            ACTION_STOP -> stopRecording()
        }
        // A start that failed, or a stop with nothing to stop, must not leave
        // an idle service behind.
        if (!active.get()) stopSelf()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        stopRecording()
        super.onDestroy()
    }

    // Start / stop
    private fun startRecording() {
        if (!active.compareAndSet(false, true)) {
            Log.w(TAG, "Already recording")
            return
        }
        failure.set(null)
        RecorderStatus.set(RecorderState.Starting)

        // Android requires the foreground call soon after a foreground start,
        // so it comes first. Any failure below removes the notification again.
        try {
            startForeground(NOTIFICATION_ID, buildNotification())
        } catch (e: Exception) {
            Log.e(TAG, "startForeground failed", e)
            failToStart("Android would not let the recorder run in the foreground: ${e.message}")
            return
        }

        val dir = RecordingFiles.directory(this)
        if (dir == null) {
            failToStart("The phone's storage is not available, so there is nowhere to save the recording.")
            return
        }

        callUuid = UUID.randomUUID().toString()
        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        wavPath = File(dir, "${callUuid}_${stamp}.wav").absolutePath
        windowsProcessed = 0
        windowsDropped = 0
        windowQueue.clear()

        val writer = StereoWavWriter(wavPath)
        try {
            writer.open()
        } catch (e: Exception) {
            Log.e(TAG, "WAV open failed", e)
            File(wavPath).delete()
            failToStart("The recording file could not be created: ${e.message}")
            return
        }
        wavWriter = writer
        Log.i(TAG, "Recording started: uuid=$callUuid wav=$wavPath")

        running.set(true)
        captureThread = Thread({ captureLoop() }, "MeetingRecorderCapture").apply {
            isDaemon = true
            start()
        }
        consumerThread = Thread({ stereoWriteLoop() }, "MeetingRecorderStereoWrite").apply {
            isDaemon = true
            start()
        }
    }

    /** A start that never reached the capture threads. */
    private fun failToStart(message: String) {
        RecorderStatus.set(RecorderState.Failed(message))
        active.set(false)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun stopRecording() {
        if (!active.get()) {
            Log.i(TAG, "Stop requested but nothing is recording")
            return
        }
        Log.i(TAG, "Recording stop requested, draining")
        finishRecording()
    }

    /**
     * Ends the recording once, whether the user asked or a thread gave up.
     * Joins both threads, closes the file and publishes the outcome.
     */
    private fun finishRecording() {
        if (!active.compareAndSet(true, false)) return
        running.set(false)
        RecorderStatus.set(RecorderState.Stopping)

        try { captureThread?.join(3000) } catch (_: Exception) {}
        try { consumerThread?.join(5000) } catch (_: Exception) {}

        var closeProblem: String? = null
        try {
            wavWriter?.close()
        } catch (e: Exception) {
            Log.e(TAG, "WAV close failed", e)
            closeProblem = "The recording file could not be finished: ${e.message}"
        }

        // Channel balance diagnostic. Both channels carry real audio, so
        // comparable RMS is expected. Lopsided RMS suggests a one sided
        // meeting or a blocked microphone.
        val rms = wavWriter?.channelRms()
        val frames = wavWriter?.framesWritten() ?: 0
        if (rms != null) {
            Log.i(TAG, "Channel RMS: L=${"%.1f".format(rms.leftRms)} R=${"%.1f".format(rms.rightRms)}")
        }
        Log.i(TAG, "Windows processed=$windowsProcessed dropped=$windowsDropped")

        val file = File(wavPath)
        val notes = RecordingNotes.build(
            rms ?: StereoWavWriter.ChannelRms(0.0, 0.0),
            windowsDropped,
        )
        val problem = failure.get() ?: closeProblem

        wavWriter = null
        windowQueue.clear()

        RecorderStatus.set(
            when {
                frames == 0 -> {
                    file.delete()
                    RecorderState.Failed(problem ?: "Nothing was recorded. The recording was stopped before any audio arrived.")
                }
                problem != null -> RecorderState.Failed(
                    "$problem Whatever was captured before that is saved.",
                    file,
                )
                else -> RecorderState.Saved(file, RecordingFiles.secondsOf(file), notes)
            }
        )

        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /**
     * Called from a capture or writer thread when it cannot go on. The first
     * reason wins. The recording is then finished on the main thread, which
     * keeps what was captured so far.
     */
    private fun abort(message: String) {
        failure.compareAndSet(null, message)
        running.set(false)
        mainHandler.post { finishRecording() }
    }

    // Capture thread: AudioRecord (stereo) to queue
    private fun captureLoop() {
        val minBuf = AudioRecord.getMinBufferSize(
            CAPTURE_SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_STEREO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuf <= 0) {
            Log.e(TAG, "AudioRecord getMinBufferSize returned $minBuf, aborting")
            abort("This phone cannot record 16 kHz stereo audio (the microphone query returned $minBuf).")
            return
        }
        val bufferSize = maxOf(minBuf * 2, WINDOW_SHORTS_STEREO * 2 * 4)

        val ar = try {
            AudioRecord(
                MediaRecorder.AudioSource.CAMCORDER,
                CAPTURE_SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_STEREO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize,
            )
        } catch (se: SecurityException) {
            Log.e(TAG, "AudioRecord SecurityException, RECORD_AUDIO missing?", se)
            abort("The microphone permission is missing.")
            return
        } catch (e: IllegalArgumentException) {
            Log.e(TAG, "AudioRecord rejected the stereo configuration", e)
            abort("This phone does not accept stereo recording: ${e.message}")
            return
        }
        if (ar.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord failed to initialise (state=${ar.state})")
            ar.release()
            abort("The microphone could not be opened. Another app may be using it.")
            return
        }

        try {
            ar.startRecording()
        } catch (e: IllegalStateException) {
            Log.e(TAG, "AudioRecord.startRecording failed", e)
            ar.release()
            abort("The microphone could not be started: ${e.message}")
            return
        }
        if (ar.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
            ar.release()
            abort("The microphone did not start. Another app, such as a phone call, may be using it.")
            return
        }

        audioRecord = ar
        startedAtMs = System.currentTimeMillis()
        // Only now is audio really being captured, so only now does the screen say so.
        RecorderStatus.replaceIf(
            RecorderState.Starting,
            RecorderState.Recording(File(wavPath), startedAtMs),
        )
        Log.i(TAG, "Capture loop running: source=CAMCORDER channel=STEREO bufferSize=$bufferSize")

        val window = ShortArray(WINDOW_SHORTS_STEREO)
        var filled = 0
        var emptyReads = 0

        while (running.get()) {
            val toRead = WINDOW_SHORTS_STEREO - filled
            val read = ar.read(window, filled, toRead)
            if (read <= 0) {
                Log.w(TAG, "AudioRecord.read returned $read")
                emptyReads++
                if (read < 0 || emptyReads >= MAX_EMPTY_READS) {
                    abort("The microphone stopped delivering audio (read returned $read).")
                    break
                }
                try { Thread.sleep(10) } catch (_: InterruptedException) {}
                continue
            }
            emptyReads = 0
            filled += read
            if (filled >= WINDOW_SHORTS_STEREO) {
                val snapshot = window.copyOf()
                val offered = windowQueue.offer(snapshot, 100, TimeUnit.MILLISECONDS)
                if (!offered) {
                    windowsDropped++
                    Log.w(TAG, "Queue full, the writer thread is falling behind; dropping window")
                }
                filled = 0
            }
        }

        try { ar.stop() } catch (_: Exception) {}
        ar.release()
        audioRecord = null
        Log.i(TAG, "Capture loop exited")
    }

    // Stereo write loop: queue, deinterleave, writeStereoWindow
    private fun stereoWriteLoop() {
        Log.i(TAG, "Stereo write loop running")
        val writer = wavWriter ?: return

        val left = ShortArray(WINDOW_FRAMES)
        val right = ShortArray(WINDOW_FRAMES)

        while (running.get() || windowQueue.isNotEmpty()) {
            val window = windowQueue.poll(250, TimeUnit.MILLISECONDS) ?: continue

            var i = 0
            var j = 0
            while (j < WINDOW_FRAMES) {
                left[j] = window[i]
                right[j] = window[i + 1]
                i += 2
                j += 1
            }

            try {
                writer.writeStereoWindow(left, right)
            } catch (e: Exception) {
                Log.e(TAG, "Writing the recording failed", e)
                abort("The recording could not be written. The phone may be out of storage. (${e.message})")
                break
            }
            windowsProcessed++

            if (windowsProcessed % 10 == 0) {
                Log.d(TAG, "[window $windowsProcessed] stereo write OK")
            }
        }

        Log.i(TAG, "Stereo write loop exited (processed $windowsProcessed windows, $windowsDropped dropped)")
    }

    // Foreground notification
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(
                NOTIFICATION_CHANNEL_ID,
                "Meeting Recording",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Meeting recording in progress"
                setShowBadge(false)
            }
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(ch)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setContentTitle("Meeting Recorder")
            .setContentText("Meeting recording in progress")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }
}
