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

## From the recorder to the turns, on a phone

On 14 October 2026 I ran the two halves together: the recorder on a phone, then the
server side on the file it saved. **The voices were synthetic.** I was alone, so I
wrote a made up two person meeting at an invented bakery
([android/try_it_script.md](../android/try_it_script.md)), turned it into speech with
the text to speech built into Windows, and played it from my laptop's speaker while
the app recorded on the phone. Dana, who speaks first, is Microsoft Zira and Tomas
is Microsoft David. This is not a recording of people in a room, so it says nothing
about how the method copes with real voices, overlapping speech or a noisy room. It
shows that the whole path works, from the phone to the turns. The recording is not
in this repository.

**What the recorder did.** The phone was a Ulefone Power Armor 19T on Android 12. I
pressed Start and the screen showed Recording and a running timer. I pressed Stop
after the playback ended and the screen showed Saved, 2 minutes 39 seconds of audio,
with no note under it. The file was a stereo WAV at 8 kHz and 16 bit, 5,088,044
bytes, and it opened and played. The log reported 318 windows written and none
dropped. The two channels were not copies of each other (the correlation between
them was about -0.08) and both carried sound, with RMS 928 on the left and 1258 on
the right. I do not know why a recording of one loudspeaker gives two such
different channels, and I have not looked into it. I did not test the screen off on
this phone, so I make no claim about that for it. Recording was done with the app in
front. I took the file off with `adb pull`. The Share button was on the screen, but I
did not press it on this phone, so it is untested there.

**What the method returned.** I ran `diarize_meeting.py` on that file with both keys
set. Mistral found the speakers (36 stretches of speech, 2 speakers) and transcribed
both sides, so Deepgram was not used and nothing fell back. The run took about 15
seconds: 6.7 to find the speakers, 4.3 for the agent side and 2.5 for the customer
side. It returned 13 turns, 7 for the agent and 6 for the customer:

| | Start (s) | Text |
|---|---|---|
| agent | 15.6 | Good morning, Tomas. Thanks for coming in. I'm Dana. I run the counter here at Harbor Light Bakery. You said on the phone it's about catering? |
| customer | 27.4 | Yes, good morning. We have a team lunch on the 12th of next month, and I'd like to order pastries and sandwiches for about 30 people. |
| agent | 38.0 | Lovely. 30 is a good size for us. Do you want a mix, or one kind of sandwich for everybody? |
| customer | 47.2 | mix, I think. Some vegetarian, because four of us don't eat meat, and one colleague can't have gluten. |
| agent | 56.4 | Okay, four vegetarian and one gluten-free. Our gluten-free loaf is baked on Thursdays. So for the 12th, we would bake it the day before and keep it separate from everything else. |
| customer | 69.0 | That would be perfect. What would you suggest for the pastries? |
| agent | 74.6 | Most offices like the almond croissants and the cinnamon rolls. I would do 20 croissants and 20 rolls, so there are a few left over. |
| customer | 85.0 | 40 is fine. What does that come to with the sandwiches? |
| agent | 91.3 | Sandwiches are 55 rand each box of 4, so 8 boxes is 440. Croissants and rolls are 280 together. That makes 720 rand, plus delivery. 3 street is 30 rent. So 750 rent in total. |
| customer | 115.8 | That's reasonable. Can you deliver by half past eleven? We eat at noon. |
| agent | 123.0 | Half past 11 works. I'll put you down for the 12th, delivery at 11.30, and I'll send a confirmation to your email today. |
| customer | 133.5 | Thank you, Dana. My email is tamash at northgate.example. |
| agent | 139.9 | Got it. We will see you on the 12th. Have a good day. Tamas. |

The first words are at 15.6 seconds because I started the playback some seconds
after the phone showed Recording, and the played file begins with 2 seconds of
silence.

**Against the script.** The script has 16 turns and the method returned 13. Every
returned turn is on the right side except for what went wrong in two places:

* Tomas's short question, "And delivery to Bree Street?", is missing. The agent turn
  at 91.3 seconds runs for 22.8 seconds and covers three scripted turns, Dana, Tomas
  and Dana, all under the agent. The question's words are not in it.
* Tomas's last line, "You too, goodbye.", is not in the result at all.

Some words are wrong: "Bree Street is thirty rand" came out as "3 street is 30
rent", Tomas came out as "Tamash" and "Tamas", and the "A" of "A mix" was lost. The
rest of the text matches the script, with numbers written as digits. The two lost
turns are both short, one to two seconds, and both follow a stretch where the other
speaker was talking. I ran it once. I have not tried it on this file with Deepgram,
and I do not know whether Deepgram would have done better.

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
