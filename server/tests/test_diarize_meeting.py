# Copyright (c) 2026 Arno Hart. All rights reserved.
# Published for viewing only. No licence is granted. See LICENSE.
"""Tests for the whole method, end to end. Deepgram is faked; nothing leaves the machine.

The end to end test needs ffmpeg and ffprobe on the PATH and is skipped without
them. The automated test run installs them, so it always runs there.
"""
import io
import json
import os
import shutil
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import numpy as np

import diarize_meeting
import prepare_meeting
import transcribe_sides
from errors import MeetingDiarizationError
from fakes import FakeResponse, deepgram_body, tone, word, write_wav

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def keyed(test):
    """Run a test with a made up key in both modules."""
    test = mock.patch.object(prepare_meeting, "DEEPGRAM_API_KEY", "test-key-not-real")(test)
    return mock.patch.object(transcribe_sides, "DEEPGRAM_API_KEY", "test-key-not-real")(test)


def voiced_regions(samples, rate, threshold=1000, min_gap=0.1):
    """Return [(start, end)] in seconds where the audio is not silent."""
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > threshold)
    if len(loud) == 0:
        return []
    regions = []
    start = prev = loud[0]
    for i in loud[1:]:
        if i - prev > min_gap * rate:
            regions.append((start / rate, prev / rate))
            start = i
        prev = i
    regions.append((start / rate, prev / rate))
    return regions


def dominant_freq(samples, rate):
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64)))
    return np.fft.rfftfreq(len(samples), 1 / rate)[int(np.argmax(spectrum))]


def fake_deepgram(url, params=None, headers=None, data=None, timeout=None):
    """Answers like Deepgram would for the made up tones.

    With diarize in the request it labels each voiced stretch by its pitch
    (low tone is one person, high tone the other). Without it, it returns one
    word per voiced stretch, named after where the stretch starts.
    """
    with wave.open(io.BytesIO(data), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    words = []
    for start, end in voiced_regions(samples, rate):
        a, b = int(start * rate), int(end * rate)
        if params.get("diarize") == "true":
            speaker = 0 if dominant_freq(samples[a:b], rate) < 600 else 1
            words.append(word("x", round(start, 2), round(end, 2), speaker=speaker))
        else:
            words.append(word(f"at{start:.1f}", round(start, 2), round(end, 2)))
    return FakeResponse(200, deepgram_body(words))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = diarize_meeting.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_missing_key_stops_with_clear_message(self):
        with mock.patch.object(prepare_meeting, "DEEPGRAM_API_KEY", ""), \
                mock.patch.object(transcribe_sides, "DEEPGRAM_API_KEY", ""):
            code, out, err = self.run_cli(["meeting.wav"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error: DEEPGRAM_API_KEY is not set", err)

    @keyed
    def test_missing_recording_stops(self):
        with mock.patch("shutil.which", return_value="/usr/bin/tool"):
            code, _, err = self.run_cli([os.path.join(self.dir, "nope.wav")])
        self.assertEqual(code, 1)
        self.assertIn("Recording not found", err)

    @keyed
    def test_no_turns_is_an_error(self):
        rec = os.path.join(self.dir, "meeting.wav")
        write_wav(rec, np.zeros(10, dtype=np.int16))
        empty = {"conversation": [], "total_turns": 0, "model": "nova-2",
                 "audio_duration_seconds": 1.0, "chunking_used": False}
        with mock.patch("shutil.which", return_value="/usr/bin/tool"), \
                mock.patch.object(prepare_meeting, "prepare_meeting_recording", return_value="x.wav"), \
                mock.patch.object(transcribe_sides, "transcribe_stereo", return_value=empty):
            code, _, err = self.run_cli([rec])
        self.assertEqual(code, 1)
        self.assertIn("no turns", err)

    @keyed
    def test_failure_inside_a_step_is_reported(self):
        rec = os.path.join(self.dir, "meeting.wav")
        write_wav(rec, np.zeros(10, dtype=np.int16))
        with mock.patch("shutil.which", return_value="/usr/bin/tool"), \
                mock.patch.object(prepare_meeting, "prepare_meeting_recording",
                                  side_effect=MeetingDiarizationError("Deepgram diarization returned HTTP 401: x")):
            code, out, err = self.run_cli([rec])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error: Deepgram diarization returned HTTP 401", err)


class AutomatedRunTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("CI"), "only checked in the automated test run")
    def test_end_to_end_is_not_skipped_in_the_automated_run(self):
        self.assertTrue(HAVE_FFMPEG, "the automated run must install ffmpeg and ffprobe")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg and ffprobe are not on the PATH")
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    @keyed
    def test_three_turns_from_two_made_up_voices(self):
        rate = 16000
        silence = lambda s: np.zeros(int(s * rate), dtype=np.int16)
        low = lambda s: tone(s, rate, freq=300)
        high = lambda s: tone(s, rate, freq=1000)
        # Low voice opens, high voice answers, low voice again.
        audio = np.concatenate([
            silence(0.5), low(1.0), silence(0.5), high(1.0), silence(0.5), low(1.0), silence(0.5),
        ])
        rec = os.path.join(self.dir, "made_up_meeting.wav")
        write_wav(rec, audio, rate=rate)
        out_file = os.path.join(self.dir, "turns.json")

        with mock.patch("requests.post", side_effect=fake_deepgram) as post:
            code = diarize_meeting.main([rec, "--out", out_file])

        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 3)  # diarize once, then one call per side
        self.assertEqual(post.call_args_list[0].kwargs["params"]["diarize"], "true")
        with open(out_file, encoding="utf-8") as f:
            result = json.load(f)

        turns = result["turns"]
        self.assertEqual([t["speaker"] for t in turns], ["agent", "customer", "agent"])
        self.assertEqual([t["text"] for t in turns], ["at0.5", "at2.0", "at3.5"])
        for t, expected in zip(turns, [0.5, 2.0, 3.5]):
            self.assertAlmostEqual(t["start"], expected, delta=0.05)
        self.assertAlmostEqual(result["audio_duration_seconds"], 5.0, delta=0.05)
        self.assertEqual(result["model"], "nova-2")


if __name__ == "__main__":
    unittest.main()
