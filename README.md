# Meeting Diarization

Turns one recording of a meeting into a conversation with two roles, an agent and
a customer, turn by turn, in the order the words were said. Both speech steps run
on [Mistral](https://mistral.ai) by default, with [Deepgram](https://deepgram.com)
as the backup, using your own keys.

## Why

I am the founder of [Wappari](https://wappari.com/), where every conversation a
business has with a customer is brought down to the same shape: text attributed to
the customer or to the agent, turn by turn. Phone calls arrive in that shape almost
for free, because the agent is on one channel of the recording and the customer on
the other. A meeting does not. It is one microphone in a room, everyone mixed
together.

So I built a way to give a meeting the same shape as a phone call. Find who speaks
when, put the first speaker on one channel and everyone else on the other, and from
there the meeting goes through exactly the same transcription path as a call.

The code in this repository is taken from Wappari's working meeting pipeline. I
have not redesigned it. Mistral goes first and Deepgram takes over when Mistral
fails, in the same order and on the same conditions as on the platform. I removed
what cannot be public (addresses, keys, the platform's own fields, the step that
hands the result to the rest of Wappari, and the other speech services the
platform can fall back to). Where the live pipeline carries on quietly after a
failure, this version stops with a clear error instead, and when the backup takes
over it says so.

Arno Hart · [LinkedIn](https://www.linkedin.com/in/arnohart/)

## The recorder

The method starts from one recording of a meeting, so this repository also holds
the app that makes one. It is the meeting recorder from the Android app I built at
Wappari, lifted out and kept as it was built: a service that keeps recording with
the screen off, and the writer that produces the file. I added one small screen so
you can run it, with a Start button, a Stop button, and a Share button for getting
the saved file off the phone.

The service captures stereo from the phone's microphones at 16 kHz and the writer
saves a 16 bit stereo WAV at 8 kHz, with the two channels exactly as the phone gave
them. Nothing on the phone works out who spoke. That is left to the server side, on
purpose. The file is saved in the app's own folder, so the app needs no storage
permission, and it never leaves the phone unless you press Share.

I removed everything that was not the recorder: the upload and the key that went
with it, the login, the business and customer details, the contact picker, calling,
the wake word, and every server address and name. Where the recorder in the app
carried on quietly after a failure, this one says so on the screen. The places are
below. The screen shows the real state of the recording at every moment, including
after the phone is rotated.

**Where it behaves differently from the one in the app**

1. If the microphone cannot be opened (the phone refuses stereo, the permission is
   missing, another app has the microphone), the app now says so and removes its
   notification. Before, it logged the reason, kept the notification, and showed
   nothing.
2. If the phone has no storage to save to, or the file cannot be created, it says
   so. Before, the service crashed.
3. If writing fails part way, for example because the phone is full, it keeps what
   it has and says so. Before, the error was not caught and the app crashed.
4. If the microphone stops delivering audio, it stops and says so. Before, it spun
   in a loop forever.
5. If the file cannot be finished, it says so. Before, that was only logged.
6. Pressing Stop when nothing is recording no longer leaves a notification and an
   idle service behind.
7. A recording that is stopped before any audio arrives is reported and removed,
   instead of leaving a file with only a header.
8. A recording that comes out silent, with one dead channel, or with dropped
   windows says so on the screen. Before, the first two were only logged and the
   dropped windows were counted and never reported.
9. If the app is killed while recording, the file is left with its sizes unset. On
   the next start the app finishes the header, so the file plays, and says the
   recording was cut short.
10. The screen says Recording only once audio is really arriving. It says so if the
    recorder has not started after five seconds, and if notifications are off.

The recorder in the app also sent the file to a server and kept a record of the
customer chosen. None of that is here.

**Android versions.** It supports Android 7.0 (API 24) and later, and is built
against Android 15 (API 35). The versions matter in two places. From Android 13 the
app also asks to show notifications, and recording works without that permission.
From Android 14 the foreground service has to declare the microphone, which it does.

## What happened on a real recording

On 13 October 2026 I ran it on a real meeting recording, 4 minutes 29 seconds long,
8 kHz mono. Neither the recording nor anything produced from it is in this
repository.

I ran it three ways, one straight after the other:

1. **Mistral only.** Only the Mistral key was set.
2. **Deepgram only.** Only the Deepgram key was set. The method reported that
   Mistral was not configured for both steps and that Deepgram was used instead.
3. **Mistral made to fail.** Both keys were set, but the Mistral key was replaced
   by an invalid one. Mistral refused both steps (HTTP 401), Deepgram took over
   both, and the method reported both fallbacks. The turns were identical to the
   Deepgram only run.

All three runs finished. Nothing failed that was not meant to.

| | Mistral | Deepgram |
|---|---|---|
| Model | `voxtral-mini-latest` | `nova-2` |
| Speakers found | 3; the third speaks for 2.6 seconds in all | 2 |
| Stretches of speech | 105 | 26 |
| First speaker | from 0.6 seconds | from 0.4 seconds; the same person |
| Seconds on the agent side / customer side | 125.7 / 97.1 | 140.2 / 111.2 |
| Turns | 24 (12 agent, 12 customer) | 26 (13 agent, 13 customer) |
| Words on the agent side / customer side | 360 / 330 | 383 / 332 |
| Punctuation | on every turn | on every turn |

The two vendors put speech on the same side 99% of the time (219 of the 222
seconds both of them assigned). Their turns line up one for one for the first 24,
with start times within a second of each other. The difference is at the very end:
Deepgram splits the last eight seconds into three short turns (customer, agent,
customer), and Mistral keeps them as one customer turn. Mistral's third speaker
lands on the customer side, as everyone after the first speaker does. Mistral's
stretches of speech are shorter and fit the words more tightly, which is why it
puts fewer seconds on each side. Nobody has yet listened through the recording to
judge which vendor is closer to who really spoke.

**Timings, in seconds:**

| Step | Mistral only | Deepgram only | Mistral made to fail |
|---|---|---|---|
| Find the speakers | 6.9 | 23.6 | 4.8 (0.8 Mistral refusing, 4.0 Deepgram) |
| Transcribe the agent side | 4.1 | 28.6 | 3.6 after Mistral refused in 1.1 |
| Transcribe the customer side | 3.6 | 3.8 | 4.0 |
| Whole run | 15.0 | 57.2 | 14.0 |

Deepgram was much slower in the Deepgram only run than in the run a minute
later, on identical requests. Earlier the same day the same requests took about
4 seconds each. That is Deepgram's response time varying, not the method.

**Deepgram's newer diarization option.** Earlier the same day, on an earlier
version of this code that used Deepgram for both steps, I compared Deepgram's
deprecated `diarize=true`, which this code uses, against `diarize_model=latest`,
which Deepgram documents today. The `diarize=true` run gave exactly the same turns
as the Deepgram runs above. With `diarize_model=latest`, Deepgram found 3 speakers
instead of 2 (the third for 0.6 seconds in all) and 39 stretches of speech instead
of 26. The first speaker was the same. It returned 25 turns instead of 26, and the
two runs put speech on the same side 96% of the time. The differences were in
three places: a short agent turn about 20 seconds in became part of the customer's
turn, a short agent turn appeared at about 214 seconds, and the run ended on the
agent instead of a short customer turn. Finding the speakers took 5.2 seconds
instead of 4.3.

## What a run costs

These figures come from each vendor's published prices on 13 October 2026, not
from an invoice. A run sends the full length of the recording three times: once to
find the speakers and once for each side. For this recording that is 13.4 minutes
of audio.

* **Mistral:** $0.003 per minute for Voxtral Mini Transcribe V2, which Mistral
  names `voxtral-mini-latest`. That makes about $0.04 for one run. Mistral's own
  usage figures in the responses add up to 13.3 minutes.
* **Deepgram:** Deepgram's pricing page no longer lists a price for `nova-2`.
  Its current pay as you go price for Nova-3 (monolingual) on recorded audio is
  $0.0043 per minute, with diarization included. At that rate one run costs about
  $0.06.
* When Mistral is refused and Deepgram takes over, the run costs what a Deepgram
  run costs.

## Quickstart

You need Python 3.10 or later, ffmpeg and ffprobe on your PATH, and a key for
Mistral, Deepgram or both.

```bash
git clone https://github.com/fastcloudza/meeting-diarization.git
cd meeting-diarization/server
pip install -r requirements.txt

export MISTRAL_API_KEY=your_mistral_key     # Windows PowerShell: $env:MISTRAL_API_KEY="your_mistral_key"
export DEEPGRAM_API_KEY=your_deepgram_key   # optional: the backup
python diarize_meeting.py path/to/meeting.m4a --out turns.json
```

Keys are read from the environment and are never written to a file. With only a
Mistral key there is no backup. With only a Deepgram key, Deepgram does both steps
and the result says that Mistral was not configured. With no key at all the run
stops before it starts.

Optional settings, also from the environment: `MISTRAL_MODEL` (default
`voxtral-mini-latest`), `MISTRAL_API_URL`, `DEEPGRAM_MODEL` (default `nova-2`) and
`DEEPGRAM_API_URL`.

If a step fails on every vendor it has a key for, the run stops with exit status 1
and a message on stderr naming each vendor and why it failed. It never returns a
partial or guessed result.

## Try the recorder

You need a phone or an emulator, a JDK 17 or later, and the Android SDK (Android
Studio brings both). From the folder `android`:

```bash
cd android
./gradlew assembleDebug          # Windows PowerShell: .\gradlew.bat assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

Open Meeting Recorder, press Start and allow the microphone, and talk. The recorder
is built to keep going with the phone locked or the screen off. Press Stop, then Share the saved
file to wherever you like, or take it off with a cable:

```bash
adb pull /sdcard/Android/data/com.arnohart.meetingdiarization/files/recordings/ .
```

The file is a stereo WAV and goes straight into the server side:

```bash
python server/diarize_meeting.py recordings/the_file.wav --out turns.json
```

[android/try_it_script.md](android/try_it_script.md) is a made up two person
meeting at an invented bakery that you can read aloud to try it.

## How it works

1. Take one recording of a meeting, in any format ffmpeg can read.
2. Find who speaks when. The recording is downmixed to 8 kHz mono and sent to
   Mistral with diarization on. If Mistral fails for any reason (no key, an error
   status, a network failure, a reply in the wrong shape, or no speakers found),
   the same file goes to Deepgram. Only the speaker labels and times are kept; the
   text from this pass is thrown away.
3. Build a two sided file. A new stereo file is written with the first person to
   speak on the left channel and everyone else on the right. Each channel is silent
   while the other side talks, and the timing is kept exactly.
4. Transcribe each side. The two channels are split apart again and each one is
   sent to Mistral on its own. If Mistral fails on either side, both sides are
   transcribed again by Deepgram, so the two sides always come from the same
   vendor. Long audio is cut into nine minute chunks with five seconds of overlap,
   and the overlap is removed again afterwards.
5. Return the turns in order. Both sides are merged by time and consecutive pieces
   from the same side are joined into one turn. The left side is the agent and the
   right side is the customer.

The first speaker is the agent because the person recording opens the meeting.

## Output

The values below are invented to show the shape. This one shows Mistral failing
and Deepgram taking over; when Mistral works, `fell_back` is `false` and
`failures` is empty.

```json
{
  "turns": [
    { "speaker": "agent", "text": "Thanks for making the time today.", "start": 0.4, "end": 2.1, "language": "en" },
    { "speaker": "customer", "text": "Happy to. Where do you want to start?", "start": 2.5, "end": 4.3, "language": "en" }
  ],
  "total_turns": 2,
  "speaker_pass": {
    "backend": "deepgram",
    "model": "nova-2",
    "fell_back": true,
    "failures": { "mistral": "Mistral diarization returned HTTP 401: {\"detail\":\"Invalid API Key\"}" }
  },
  "transcription": {
    "backend": "deepgram",
    "model": "nova-2",
    "fell_back": true,
    "failures": { "mistral": "Mistral transcription returned HTTP 401: {\"detail\":\"Invalid API Key\"}" }
  },
  "audio_duration_seconds": 4.8,
  "chunking_used": false
}
```

Each fallback is also printed as a warning on stderr. `start` and `end` are seconds
from the start of the recording. The `language` field is a fixed label, as on the
platform, not a detected language.

## Checked against the documentation

On 12 and 13 October 2026 I checked every request against each vendor's
documentation.

**Mistral**

* Authentication with `Authorization: Bearer <key>`, and the audio sent as the
  multipart `file` field, match the documentation.
* `diarize` and `timestamp_granularities` are documented and not marked as
  deprecated. Timestamps cannot be combined with `language`; this method sends
  no language and lets Mistral detect it.
* Mistral names `voxtral-mini-latest` as Voxtral Mini Transcribe V2. The older
  `voxtral-mini-2507` was deprecated on 27 February 2026 and retired on 31 May
  2026; this method does not use it.
* The documentation does not list the fields of a segment. The real run returned
  `text`, `start`, `end`, `speaker_id` and `type` on every segment, with
  `speaker_id` empty when diarization is off.
* Mistral documents recordings of up to three hours in one request, and no limit
  on file size or processing time.

**Deepgram**

* Authentication with `Authorization: Token <key>`, and the raw audio as the
  request body with `Content-Type: audio/wav`, match the documentation.
* The speaker pass uses `diarize=true`. Deepgram now marks that parameter as
  deprecated in favour of `diarize_model`. It still works and uses their first
  diarization model. I have left it as built. See the comparison above.
* `nova-2` is still listed as a model and is not marked as deprecated, though its
  price is no longer on the pricing page. Deepgram has newer models.
* No `language` is sent, so Deepgram uses its default, English.
* Deepgram's documentation ties the `punctuated_word` field to smart formatting,
  while this method asks for `punctuate`. In the real runs it was on every word.
* Deepgram returns an error for a request that takes longer than ten minutes to
  process. The speaker pass sends the whole recording in one request.

## Limits

* There are exactly two roles. The first person to speak is the agent and everyone
  else is the customer. In a meeting with three or more people, everyone except the
  first speaker ends up on the customer side.
* If someone other than the person recording speaks first, the roles come out the
  wrong way round.
* The roles are only as good as the diarization. If it merges two people or splits
  one person in two, the two sided file inherits that.
* The recording is reduced to 8 kHz mono before diarization, the same as a phone
  line. That can cost accuracy on a good microphone.
* Deepgram transcribes in English unless the model is changed. Mistral detects the
  language itself.
* Very long recordings are limited to twenty transcription chunks (about three
  hours) and by each vendor's limit on the single speaker pass.

## Consent

Only record people who have agreed to be recorded, and follow the recording laws
where you are.

## Layout

```text
android/
  app/src/main/         the recorder app
    DiarisedRecordingService.kt   the service that records, with the screen off
    StereoWavWriter.kt            the writer that produces the audio file
    RecorderState.kt              what the recorder is doing, shared with the screen
    RecordingFiles.kt             where files live, and mending one that was cut short
    MainActivity.kt               the one screen: start, stop, share
  app/src/test/         tests of the writer and the file handling
  app/src/androidTest/  a test of the writer that runs on a phone or emulator
  try_it_script.md      a made up meeting to read aloud
server/
  prepare_meeting.py    steps 2 and 3: downmix, find the speakers, build the two sided file
  transcribe_sides.py   steps 4 and 5: split the sides, transcribe each, merge in order
  diarize_meeting.py    runs the whole method on one file from the command line
  errors.py             the one error type every step raises
  tests/                tests with invented data; none of them call Mistral or Deepgram
```

## Tests

```bash
cd server
python -m unittest discover -s tests -v
```

No keys and no network are needed; every test sets its own invented keys. The
tests cover the order (Mistral first), each fallback to Deepgram, a reader with
only one of the two keys, and both stop conditions (no key at all, and every
vendor failing). Two end to end tests build a recording from two invented voices
(two tones), run the real ffmpeg steps and fake only the vendors: one where
Mistral works, and one where Mistral refuses and Deepgram takes over. They need
ffmpeg and ffprobe and are skipped without them. The automated test run on every
change installs them, so they always run there.

The app side has its own tests, which need no phone:

```bash
cd android
./gradlew testDebugUnitTest
```

They cover the writer (the header, the sizes, the 8 kHz stereo format, two windows
in a row), mending the header of a recording that was cut short, and the messages
shown about a finished recording. A further test of the writer runs on a phone or
emulator with `./gradlew connectedDebugAndroidTest`. The microphone and the service
are not covered by an automated test, because they need a real microphone. The
automated run on every change builds the app and runs the unit tests next to the
server tests.

## Licence

MIT. See [LICENSE](LICENSE).
