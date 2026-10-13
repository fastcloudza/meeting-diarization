package com.arnohart.meetingdiarization

import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * What the recorder is doing right now. The service writes it and the screen
 * reads it, so the screen shows the real state at any moment, including after
 * the phone is rotated and the activity is rebuilt.
 */
sealed interface RecorderState {
    /** Nothing is recording and nothing has been saved in this run of the app. */
    data object Idle : RecorderState

    /** Start was requested. The microphone is not delivering audio yet. */
    data object Starting : RecorderState

    /** Audio is arriving and being written to [file]. */
    data class Recording(val file: File, val startedAtMs: Long) : RecorderState

    /** Stop was requested. The file is being closed. */
    data object Stopping : RecorderState

    /** The file is complete. [notes] lists anything about it worth knowing. */
    data class Saved(val file: File, val seconds: Int, val notes: List<String>) : RecorderState

    /** Recording could not start or ended early. [file] holds whatever was captured, if anything. */
    data class Failed(val message: String, val file: File? = null) : RecorderState
}

/** The one place the state lives. The service and the activity share a process. */
object RecorderStatus {
    private val mutable = MutableStateFlow<RecorderState>(RecorderState.Idle)
    val state: StateFlow<RecorderState> = mutable

    fun set(next: RecorderState) {
        mutable.value = next
    }

    /** Change the state only if it is still [expected]. Returns whether it changed. */
    fun replaceIf(expected: RecorderState, next: RecorderState): Boolean =
        mutable.compareAndSet(expected, next)
}
