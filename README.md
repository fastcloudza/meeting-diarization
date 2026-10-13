# meeting-diarization

**Published for viewing only. This is not open source.** The source is public
so it can be read and evaluated. You may not use, run, copy, modify or
distribute it without the written permission of the author.

Author: Arno Hart. Licence: all rights reserved, see [LICENSE](LICENSE).

## What this is

This is my method for turning one recording of a meeting into a conversation
with two roles, an agent and a customer, in the order the words were said. I
built it for my own voice platform, where it runs on real meetings, and this
repository is that code taken out of the platform. I have not redesigned it.
I removed only what cannot be public: server addresses, keys, names, the
platform's own fields, and the steps that hand the result to the rest of the
platform.

The `server` folder holds the method. The phone app that records the meetings
will follow in its own folder.

## How it works

1. Take one recording of a meeting, in any format ffmpeg can read.
2. Find who speaks when. The recording is downmixed to 8 kHz mono and sent to
   Deepgram with diarization on. Only the speaker labels and word times are
   kept; the text from this pass is thrown away.
3. Build a two sided file. A new stereo file is written with the first person
   to speak on the left channel and everyone else on the right. Each channel
   is silent while the other side talks, and the timing is kept exactly.
4. Transcribe each side. The two channels are split apart again and each one
   is sent to Deepgram on its own. Long audio is cut into nine minute chunks
   with five seconds of overlap, and the overlap is removed again afterwards.
5. Return the turns in order. Both sides are merged by time and consecutive
   pieces from the same side are joined into one turn. The left side is the
   agent and the right side is the customer.

The first speaker is the agent because the person recording opens the
meeting.

Why not take the text straight from the diarization pass? Because the two
sided file is the same shape as a two channel phone call recording, so a
meeting goes through exactly the same transcription path as a phone call.

| File | What it does |
|---|---|
| `server/prepare_meeting.py` | Steps 2 and 3: downmix, diarize, build the two sided file |
| `server/transcribe_sides.py` | Steps 4 and 5: split the sides, transcribe, merge |
| `server/diarize_meeting.py` | Runs the whole method on one file from the command line |
| `server/errors.py` | The one error type every step raises |
| `server/tests/` | Tests that run with made up data and never call Deepgram |

## Running it

These steps are for people who have the author's written permission to run
the software (see [LICENSE](LICENSE)).

You need Python 3.10 or newer, ffmpeg and ffprobe on your PATH, and your own
Deepgram account. Your Deepgram key is read from the environment and is never
written in any file. Each run is billed to your Deepgram account: the
recording is sent once for diarization and each side is sent once more for
transcription.

```bash
cd server
pip install -r requirements.txt
export DEEPGRAM_API_KEY=your_key_here
python diarize_meeting.py path/to/meeting.m4a --out turns.json
```

Optional settings, also from the environment: `DEEPGRAM_MODEL` (default
`nova-2`) and `DEEPGRAM_API_URL` (default `https://api.deepgram.com/v1/listen`).

If any step fails, the run stops with exit status 1 and a message on stderr
saying which step and why. It never returns a partial or guessed result.

Run the tests (no key and no network needed):

```bash
cd server
python -m unittest discover -s tests -v
```

## Output

The values below are made up to show the shape, not taken from a real meeting.

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

## What has been run for real and what has not

**Run for real:** nothing yet. This published version has not yet been run
against Deepgram. I will update this section after the first real run.

**Tested:** every step with made up data in the shape Deepgram returns,
including an end to end test that builds a recording from two made up
voices (two tones), runs the real ffmpeg steps, and fakes only Deepgram.
The automated test run does this on every change.

**Checked against Deepgram's documentation only (12 October 2026):**

* Authentication with `Authorization: Token <key>` and the raw audio as the
  request body with `Content-Type: audio/wav` match the documentation.
* The diarization pass uses `diarize=true`. The documentation now marks that
  parameter as deprecated in favour of `diarize_model`, and says
  `diarize=true` still works and uses their first diarization model. I have
  left it as built.
* `nova-2` is still listed as an available model and is not marked as
  deprecated. Deepgram has newer models.
* No `language` is sent, so Deepgram uses its default, English. The
  `language` field in the output records that.
* The documentation ties the `punctuated_word` field to smart formatting,
  while this method asks for `punctuate`. The code uses `punctuated_word`
  when it is there and the plain word when it is not.
* Deepgram returns an error for requests that take longer than ten minutes
  to process. The diarization pass sends the whole recording in one request.

## Limits

* There are exactly two roles. The first person to speak is the agent and
  everyone else is the customer. In a meeting with three or more people, all
  of them except the first speaker end up on the customer side.
* If someone other than the person recording speaks first, the roles come
  out the wrong way round.
* The roles are only as good as Deepgram's diarization. If it merges two
  people or splits one person in two, the two sided file inherits that.
* The recording is reduced to 8 kHz mono before diarization, the same as a
  phone line. That can cost accuracy on a good microphone.
* Both sides are transcribed in English unless the model is changed.
* Very long recordings are limited to twenty transcription chunks (about
  three hours) and by Deepgram's processing time limit on the single
  diarization request.

## Consent

Only record people who have agreed to be recorded, and follow the recording
laws where you are.

## Licence and author

Copyright (c) 2026 Arno Hart. All rights reserved. No licence is granted; see
[LICENSE](LICENSE). To request permission or a commercial licence, contact the
author through his GitHub profile.
