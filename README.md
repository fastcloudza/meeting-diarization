# Meeting Diarization

A phone app that records a meeting, and a server side that turns the recording into
a conversation: who said what, in order, as an agent and a customer.

## The problem

A meeting recorded on a phone is one mixed sound. A phone has more than one
microphone, but each of them hears everyone in the room, so the phone cannot split
the recording by speaker. On a phone call it is different. The two sides arrive
separately, so each side is a speaker for free. In a room that is impossible on the
phone side.

So the separation has to happen afterwards, on a server, with a diarization service
that works out who spoke when. Until that is done the recording cannot go anywhere
as a conversation between an agent and a customer.

## What I built

I am the founder of [Wappari](https://wappari.com/), where every conversation a
business has with a customer is brought down to the same shape: text from the
customer or from the agent, turn by turn. This is how I get a meeting into that
shape. The code is taken from Wappari's working meeting pipeline, with what cannot
be public removed.

* **The recorder** (`android/`) is an Android app with one screen. It records the
  meeting, is built to keep going with the screen off, and saves a stereo WAV on the phone.
  It does not try to split the speakers. You Share the file off the phone when you
  are done.
* **The server side** (`server/`) sends the file to a diarization service and works
  out who spoke when. The first speaker is the agent, because the person recording
  opens the meeting. Everyone else is the customer. It then transcribes each side
  on its own and returns the meeting as ordered agent and customer turns, ready to
  feed into a conversation platform.

It uses [Mistral](https://mistral.ai) first and [Deepgram](https://deepgram.com) as
the backup, with your own keys.

## How to run it

The app needs a JDK 17 or later and the Android SDK, and runs on Android 7.0 and
later.

```bash
cd android
./gradlew assembleDebug          # gradlew.bat on Windows
adb install app/build/outputs/apk/debug/app-debug.apk
```

Open Meeting Recorder, press Start, talk, press Stop, and Share the file.
[android/try_it_script.md](android/try_it_script.md) is a made up meeting you can
read aloud.

The server side needs Python 3.10 or later, ffmpeg and ffprobe, and a Mistral or
Deepgram key:

```bash
cd server
pip install -r requirements.txt
export MISTRAL_API_KEY=your_key      # or DEEPGRAM_API_KEY
python diarize_meeting.py meeting.wav --out turns.json
```

`turns.json` holds the turns in order, each with its speaker, text and times.

## Has it run

Yes, once for real on a phone, a Ulefone Power Armor 19T on Android 12. I was alone,
so the meeting was a made up conversation at an invented bakery, spoken by two
synthetic voices played from my laptop while the app recorded. The recording came
back as ordered turns with the agent and the customer on the right sides almost
all the way through, and most words, numbers and names right. Two short turns were
lost and a few words were wrong. It does not show how the method copes with real
people in a room, which I have not yet tested. The recording is not in this
repository.

## Limits

* There are exactly two roles. The first person to speak is the agent and everyone
  else is the customer.
* If someone other than the person recording speaks first, the roles come out the
  wrong way round.
* The roles are only as good as the diarization. If it merges two people or splits
  one in two, the result inherits that.
* Only record people who have agreed to be recorded, and follow the recording laws
  where you are.

More detail is in [NOTES.md](NOTES.md).

## Licence

MIT. See [LICENSE](LICENSE).

Arno Hart · [LinkedIn](https://www.linkedin.com/in/arnohart/)
