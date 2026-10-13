package com.arnohart.meetingdiarization

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import kotlinx.coroutines.delay
import java.io.File

/**
 * One screen: start, stop, and a way to get the saved file off the phone.
 *
 * The screen holds no recording state of its own. It shows [RecorderStatus],
 * which the service keeps up to date, so after a rotation it shows the same
 * thing it showed before.
 */
class MainActivity : ComponentActivity() {

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        if (hasMicrophonePermission()) {
            beginRecording()
        } else {
            RecorderStatus.set(
                RecorderState.Failed(
                    "The microphone permission was refused, so recording cannot start. " +
                        "Allow Microphone for this app in the phone's settings and try again."
                )
            )
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // A fresh run of the app: show the newest recording already on the
        // phone, so a recording made before the app was killed can still be shared.
        if (RecorderStatus.state.value == RecorderState.Idle) {
            RecordingFiles.recoverLatest(applicationContext)?.let { RecorderStatus.set(it) }
        }

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val state by RecorderStatus.state.collectAsState()
                    RecorderScreen(
                        state = state,
                        onStart = ::onStartTapped,
                        onStop = ::stopRecording,
                        onShare = ::shareFile,
                    )
                }
            }
        }
    }

    private fun hasMicrophonePermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun onStartTapped() {
        if (hasMicrophonePermission()) {
            beginRecording()
            return
        }
        val wanted = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            wanted += Manifest.permission.POST_NOTIFICATIONS
        }
        permissionLauncher.launch(wanted.toTypedArray())
    }

    private fun beginRecording() {
        RecorderStatus.set(RecorderState.Starting)
        val intent = Intent(this, DiarisedRecordingService::class.java).apply {
            action = DiarisedRecordingService.ACTION_START
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
        } catch (e: Exception) {
            RecorderStatus.set(RecorderState.Failed("The recorder service could not be started: ${e.message}"))
        }
    }

    private fun stopRecording() {
        val intent = Intent(this, DiarisedRecordingService::class.java).apply {
            action = DiarisedRecordingService.ACTION_STOP
        }
        try {
            startService(intent)
        } catch (e: Exception) {
            RecorderStatus.set(RecorderState.Failed("The recorder service could not be reached to stop it: ${e.message}"))
        }
    }

    /** Hands the file to the share sheet. Returns a message if that could not be done. */
    private fun shareFile(file: File): String? {
        return try {
            val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
            val send = Intent(Intent.ACTION_SEND).apply {
                type = "audio/wav"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(send, "Share recording"))
            null
        } catch (e: ActivityNotFoundException) {
            "No app on this phone can receive the file. It is still at ${file.absolutePath}."
        } catch (e: IllegalArgumentException) {
            "The file could not be shared: ${e.message}"
        }
    }
}

@Composable
private fun RecorderScreen(
    state: RecorderState,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onShare: (File) -> String?,
) {
    val context = LocalContext.current

    // The service answers a start within a moment. If it never does, say so.
    LaunchedEffect(state) {
        if (state == RecorderState.Starting) {
            delay(5000)
            RecorderStatus.replaceIf(
                RecorderState.Starting,
                RecorderState.Failed("The recorder did not start within 5 seconds."),
            )
        }
    }

    // Elapsed time is worked out from the start time the service published,
    // so it stays right across a rotation.
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(state) {
        while (state is RecorderState.Recording) {
            now = System.currentTimeMillis()
            delay(500)
        }
    }

    var shareProblem by remember { mutableStateOf<String?>(null) }
    val fileToShare: File? = when (state) {
        is RecorderState.Saved -> state.file
        is RecorderState.Failed -> state.file
        else -> null
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Meeting Recorder", fontSize = 24.sp, fontWeight = FontWeight.SemiBold)

        when (state) {
            RecorderState.Idle -> Status("Ready", "Nothing has been recorded yet.")
            RecorderState.Starting -> Status("Starting", "Waiting for the microphone.")
            is RecorderState.Recording -> {
                val seconds = ((now - state.startedAtMs) / 1000).coerceAtLeast(0)
                Status("Recording", "%d:%02d".format(seconds / 60, seconds % 60))
                if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
                    Text(
                        "Notifications are off for this app. Recording still runs with the screen " +
                            "off, but the phone shows no notice that it is recording.",
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
            RecorderState.Stopping -> Status("Stopping", "Closing the file.")
            is RecorderState.Saved -> {
                Status("Saved", "%d:%02d of audio".format(state.seconds / 60, state.seconds % 60))
                Text(state.file.name)
                Text("Saved in ${state.file.parent}", fontSize = 12.sp)
                state.notes.forEach { Text(it, color = MaterialTheme.colorScheme.error) }
            }
            is RecorderState.Failed -> {
                Status("Not recording", "")
                Text(state.message, color = MaterialTheme.colorScheme.error)
                state.file?.let { Text("Saved anyway: ${it.name}") }
            }
        }

        Spacer(Modifier.height(8.dp))

        val recording = state is RecorderState.Recording
        val busy = state == RecorderState.Starting || state == RecorderState.Stopping
        if (recording) {
            Button(
                onClick = onStop,
                modifier = Modifier.fillMaxWidth().height(64.dp),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
            ) { Text("Stop", fontSize = 18.sp) }
        } else {
            Button(
                onClick = {
                    shareProblem = null
                    onStart()
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth().height(64.dp),
            ) { Text("Start", fontSize = 18.sp) }
        }

        if (fileToShare != null && !recording && !busy) {
            OutlinedButton(
                onClick = { shareProblem = onShare(fileToShare) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Share the saved file") }
            shareProblem?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
}

@Composable
private fun Status(label: String, detail: String) {
    Column {
        Text(label, fontSize = 20.sp, fontWeight = FontWeight.Medium)
        if (detail.isNotEmpty()) Text(detail, fontSize = 16.sp)
    }
}
