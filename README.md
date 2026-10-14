# Meeting Diarization

Turns one recording of a meeting into a conversation between an agent and a
customer, turn by turn, in the order the words were said. It uses
[Mistral](https://mistral.ai), with [Deepgram](https://deepgram.com) as the backup,
on your own keys.

## Why

I am the founder of [Wappari](https://wappari.com/), where every conversation a
business has with a customer is brought down to the same shape: text attributed to
the customer or to the agent, turn by turn. Phone calls arrive in that shape almost
for free, because the agent is on one channel of the recording and the customer on
the other. A meeting does not. However many microphones a phone has, each one
hears everyone in the room, so no channel belongs to one person. The split by
speaker cannot happen on the phone.

So I built a way to give a meeting the same shape as a phone call. The result is
ordered agent and customer turns, ready to go into a conversation platform the
same way a call does. Find who speaks when, put the first speaker on one side and
everyone else on the other, and from there the meeting goes through exactly the
same transcription path as a call.

The code is taken from Wappari's working meeting pipeline, with everything private
removed. This repository also holds the Android recorder the method starts from.

Arno Hart · [LinkedIn](https://www.linkedin.com/in/arnohart/)

## Does it work

On 14 October 2026 I ran the whole path: the recorder on a phone, then the server
side on the file it saved. The meeting was a made up conversation at an invented
bakery ([android/try_it_script.md](android/try_it_script.md)), played as synthetic
voices from a laptop speaker. It took about 15 seconds.

Synthetic voices from one speaker say nothing about real people talking over each
other in a noisy room.

If Mistral fails, Deepgram takes over automatically. I tested that by giving it a
bad Mistral key: Deepgram took over and the result said so.

A run costs about 4 cents on Mistral for a 4.5 minute meeting.

The full results, the vendor comparison and the documentation checks are in
[docs/notes.md](docs/notes.md).

## Quickstart

You need Python 3.10 or later, ffmpeg (on Windows: `winget install ffmpeg`) and a
key for Mistral, Deepgram or both.

```bash
git clone https://github.com/fastcloudza/meeting-diarization.git
cd meeting-diarization/server
pip install -r requirements.txt

export MISTRAL_API_KEY=your_mistral_key     # Windows PowerShell: $env:MISTRAL_API_KEY="your_mistral_key"
export DEEPGRAM_API_KEY=your_deepgram_key   # optional: the backup
python diarize_meeting.py path/to/meeting.m4a --out turns.json
```

Keys are read from the environment and never written to a file. If every vendor
you have a key for fails, the run stops with a clear error and never returns a
partial result.

## Try the recorder

You need a phone or an emulator, a JDK 17 or later, and the Android SDK (Android
Studio brings both).

```bash
cd android
./gradlew assembleDebug          # Windows PowerShell: .\gradlew.bat assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

Open Meeting Recorder, press Start, and talk. Press Stop, then Share the saved file,
and run it through the server side:

```bash
python server/diarize_meeting.py the_file.wav --out turns.json
```

## How it works

1. Find who speaks when. The recording goes to Mistral with diarization on, or to
   Deepgram if Mistral fails.
2. Build a two sided file, like a phone call: the first person to speak on one
   channel, everyone else on the other, with the timing kept exactly.
3. Transcribe each side on its own.
4. Merge both sides by time into turns. The first speaker is the agent, because the
   person recording opens the meeting.

## Output

```json
{
  "turns": [
    { "speaker": "agent", "text": "Thanks for making the time today.", "start": 0.4, "end": 2.1 },
    { "speaker": "customer", "text": "Happy to. Where do you want to start?", "start": 2.5, "end": 4.3 }
  ]
}
```

The full output also records which vendor did each step and whether it fell back.

## Limits

* There are two roles. The first person to speak is the agent and everyone else is
  the customer, so a meeting with three or more people puts everyone after the
  first speaker on the customer side.
* If someone other than the person recording speaks first, the roles come out the
  wrong way round.
* The result is only as good as the diarization. If it merges two people or splits
  one in two, the turns inherit that.

## Consent

Only record people who have agreed to be recorded, and follow the recording laws
where you are.

## Tests

```bash
cd server && python -m unittest discover -s tests -v
cd android && ./gradlew testDebugUnitTest
```

No keys and no network are needed.

## Licence

MIT. See [LICENSE](LICENSE).
