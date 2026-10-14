# Notes

Detail that does not belong on the front page.

## The recorder

It is the meeting recorder from the Android app, kept as it was built: a foreground
service that captures 16 kHz stereo from the camcorder microphone source, and a
writer that saves a 16 bit stereo WAV at 8 kHz. The channels are the phone's two
captures, not attributed to anyone. Files go to the app's own folder, so no storage
permission is needed.

I removed the upload and its key, the login, the business and customer details, the
contact picker, calling and the wake word. Where the app carried on quietly after a
failure, this version says so on the screen. The places:

1. The microphone cannot be opened: a message, and the notification is removed.
2. No storage, or the file cannot be created: a message. The app crashed before.
3. Writing fails part way: what was captured is kept and a message is shown.
4. The microphone stops delivering audio: it stops and says so.
5. The file header cannot be finished: a message. It was only logged before.
6. Stop with nothing recording leaves nothing behind.
7. Stopped before any audio: reported, and the empty file is removed.
8. A silent recording, one dead channel, or dropped windows: shown on the screen.
9. The app killed while recording: on the next start the header is finished so the
   file plays, with a note that it was cut short.
10. The screen says Recording only once audio arrives, says so if the recorder has
    not started after five seconds, and shows the true state after a rotation.

I have run it on one real phone (Android 12) and on an Android 16 emulator, and on
no other version. I did not test the Share button or screen off recording on the
phone. The two channels from that phone were not copies of each other, which I have
not explained.

## The server side

* Mistral is tried first for finding the speakers and for transcription. If it
  fails for any reason, Deepgram takes over, and both sides always come from the
  same vendor. If every vendor fails, the run stops with an error naming each.
* The recording is reduced to 8 kHz mono before diarization, like a phone line.
  Long audio is cut into nine minute chunks with five seconds of overlap.
* Deepgram speaker finding uses `diarize=true`, which Deepgram now marks as
  deprecated in favour of `diarize_model`. I left it as built. On one earlier
  recording `diarize_model=latest` found a third speaker for under a second and
  moved a few short turns.
* Deepgram transcribes in English unless the model is changed. Mistral detects the
  language itself.
* Settings come from the environment: `MISTRAL_API_KEY`, `DEEPGRAM_API_KEY`,
  `MISTRAL_MODEL`, `DEEPGRAM_MODEL`, `MISTRAL_API_URL` and `DEEPGRAM_API_URL`. Keys
  are never written to a file.

## Tests

```bash
cd server && python -m unittest discover -s tests -v
cd android && ./gradlew testDebugUnitTest
```

Neither needs a key or a phone. The server tests use invented data and fake the
vendors, and need ffmpeg. The app tests cover the WAV writer and the handling of a
recording that was cut short. A further writer test runs on a phone or emulator with
`./gradlew connectedDebugAndroidTest`. The microphone and the service are checked by
making a real recording, not by an automated test. The automated run on every change
builds and tests both sides.
