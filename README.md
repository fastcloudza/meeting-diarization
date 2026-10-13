# Meeting Diarization

Turns one recording of a meeting into a conversation with two roles, an agent and
a customer, turn by turn, in the order the words were said. Both speech steps run
on [Deepgram](https://deepgram.com) with your own key.

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
have not redesigned it. I removed what cannot be public (addresses, keys, the
platform's own fields and the step that hands the result to the rest of Wappari)
and made both speech steps use Deepgram. Where the live pipeline carries on quietly
after a failure, this version stops with a clear error instead.

Arno Hart · [LinkedIn](https://www.linkedin.com/in/arnohart/)

## What happened on a real recording

On 13 October 2026 I ran it on a real meeting recording, 4 minutes 29 seconds long,
8 kHz mono. Neither the recording nor anything produced from it is in this
repository.

**As built, it worked first time.** Using `diarize=true` and `nova-2`, Deepgram
found 2 speakers in 26 stretches of speech. The method returned 26 turns,
alternating agent and customer, 13 each. Every turn came back punctuated:
Deepgram put `punctuated_word` on every word, even though only `punctuate=true`
is asked for. The whole run took 13.3 seconds:

| Step | Seconds |
|---|---|
| Downmix to 8 kHz mono | 0.7 |
| Find the speakers (Deepgram) | 4.3 |
| Build the two sided file | under 0.1 |
| Split the two sides | 0.2 |
| Transcribe the agent side (Deepgram) | 4.3 |
| Transcribe the customer side (Deepgram) | 3.8 |

**Then with the option Deepgram documents today.** Straight after that, I ran the
same recording through the same code again, but with the speaker pass sending
`diarize_model=latest` in place of the deprecated `diarize=true`. Nothing else
changed.

| | `diarize=true`, as built | `diarize_model=latest` |
|---|---|---|
| Speakers found | 2 | 3; the third speaks for 0.6 seconds in all |
| Stretches of speech | 26 | 39 |
| First speaker | 0.4 to 4.9 seconds | the same stretch |
| Seconds on the agent side / customer side | 140.2 / 111.2 | 144.1 / 102.3 |
| Turns | 26 (13 agent, 13 customer) | 25 (13 agent, 12 customer) |
| Words on the agent side / customer side | 383 / 332 | 401 / 310 |
| Punctuation | on every turn | on every turn |
| Finding the speakers | 4.3 seconds | 5.2 seconds |
| Whole run | 13.3 seconds | 13.8 seconds |

The two runs put speech on the same side 96% of the time (237 of the 246 seconds
both of them assigned). The differences are in three places:

* About 20 seconds in, a short agent turn in the first run becomes part of the
  customer's turn in the second.
* At about 214 seconds, the second run finds a short agent turn inside what the
  first run kept as one customer turn.
* The first run ends with a short customer turn at about 264 seconds. The
  second run ends on the agent.

The third speaker in the second run lands on the customer side, as everyone
after the first speaker does. Nobody has yet listened through the recording to
judge which run is closer to who really spoke.

Nothing failed in either run.

## Quickstart

You need Python 3.10 or later, ffmpeg and ffprobe on your PATH, and a Deepgram API
key. Each run is billed to your Deepgram account: the recording is sent once to find
the speakers and each side is sent once more to be transcribed.

```bash
git clone https://github.com/fastcloudza/meeting-diarization.git
cd meeting-diarization/server
pip install -r requirements.txt

export DEEPGRAM_API_KEY=your_key_here     # Windows PowerShell: $env:DEEPGRAM_API_KEY="your_key_here"
python diarize_meeting.py path/to/meeting.m4a --out turns.json
```

The key is read from the environment and is never written to a file. Two optional
settings, also from the environment: `DEEPGRAM_MODEL` (default `nova-2`) and
`DEEPGRAM_API_URL` (default `https://api.deepgram.com/v1/listen`).

If any step fails, the run stops with exit status 1 and a message on stderr saying
which step and why. It never returns a partial or guessed result.

## How it works

1. Take one recording of a meeting, in any format ffmpeg can read.
2. Find who speaks when. The recording is downmixed to 8 kHz mono and sent to
   Deepgram with diarization on. Only the speaker labels and word times are kept;
   the text from this pass is thrown away.
3. Build a two sided file. A new stereo file is written with the first person to
   speak on the left channel and everyone else on the right. Each channel is silent
   while the other side talks, and the timing is kept exactly.
4. Transcribe each side. The two channels are split apart again and each one is
   sent to Deepgram on its own. Long audio is cut into nine minute chunks with five
   seconds of overlap, and the overlap is removed again afterwards.
5. Return the turns in order. Both sides are merged by time and consecutive pieces
   from the same side are joined into one turn. The left side is the agent and the
   right side is the customer.

The first speaker is the agent because the person recording opens the meeting.

## Output

The values below are invented to show the shape.

```json
{
  "turns": [
    { "speaker": "agent", "text": "Thanks for making the time today.", "start": 0.4, "end": 2.1, "language": "en" },
    { "speaker": "customer", "text": "Happy to. Where do you want to start?", "start": 2.5, "end": 4.3, "language": "en" }
  ],
  "total_turns": 2,
  "model": "nova-2",
  "audio_duration_seconds": 4.8,
  "chunking_used": false
}
```

`start` and `end` are seconds from the start of the recording.

## Checked against Deepgram's documentation

On 12 October 2026 I checked every Deepgram request against Deepgram's
documentation.

* Authentication with `Authorization: Token <key>`, and the raw audio as the
  request body with `Content-Type: audio/wav`, match the documentation.
* The speaker pass uses `diarize=true`. Deepgram now marks that parameter as
  deprecated in favour of `diarize_model`. It still works and uses their first
  diarization model. I have left it as built. See the comparison above.
* `nova-2` is still listed and not marked as deprecated. Deepgram has newer models.
* No `language` is sent, so Deepgram uses its default, English.
* Deepgram's documentation ties the `punctuated_word` field to smart formatting,
  while this method asks for `punctuate`. The code uses `punctuated_word` when it
  is there and the plain word when it is not. In the real run it was on every
  word.
* Deepgram returns an error for a request that takes longer than ten minutes to
  process. The speaker pass sends the whole recording in one request.

## Limits

* There are exactly two roles. The first person to speak is the agent and everyone
  else is the customer. In a meeting with three or more people, everyone except the
  first speaker ends up on the customer side.
* If someone other than the person recording speaks first, the roles come out the
  wrong way round.
* The roles are only as good as Deepgram's diarization. If it merges two people or
  splits one person in two, the two sided file inherits that.
* The recording is reduced to 8 kHz mono before diarization, the same as a phone
  line. That can cost accuracy on a good microphone.
* Both sides are transcribed in English unless the model is changed.
* Very long recordings are limited to twenty transcription chunks (about three
  hours) and by Deepgram's processing time limit on the single speaker pass.

## Consent

Only record people who have agreed to be recorded, and follow the recording laws
where you are.

## Layout

```text
server/
  prepare_meeting.py    steps 2 and 3: downmix, find the speakers, build the two sided file
  transcribe_sides.py   steps 4 and 5: split the sides, transcribe each, merge in order
  diarize_meeting.py    runs the whole method on one file from the command line
  errors.py             the one error type every step raises
  tests/                tests with invented data; none of them call Deepgram
```

## Tests

```bash
cd server
python -m unittest discover -s tests -v
```

No key and no network are needed. The end to end test builds a recording from two
invented voices (two tones), runs the real ffmpeg steps and fakes only Deepgram. It
needs ffmpeg and ffprobe and is skipped without them. The automated test run on
every change installs them, so it always runs there.

## Licence

MIT. See [LICENSE](LICENSE).
