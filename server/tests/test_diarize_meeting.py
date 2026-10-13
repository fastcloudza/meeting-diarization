"""Tests for the whole method, end to end. Mistral and Deepgram are faked; nothing leaves the machine.

The end to end tests need ffmpeg and ffprobe on the PATH and are skipped without
them. The automated test run installs them, so they always run there.
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
from fakes import (FakeResponse, deepgram_body, mistral_body, patch_keys, segment, tone,
                   word, write_wav)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


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


def regions_of(wav_bytes):
    """Each voiced stretch of a WAV as (start, end, speaker number by pitch)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    out = []
    for start, end in voiced_regions(samples, rate):
        a, b = int(start * rate), int(end * rate)
        speaker = 0 if dominant_freq(samples[a:b], rate) < 600 else 1
        out.append((round(start, 2), round(end, 2), speaker))
    return out


def fake_vendors(mistral_status=200):
    """Answers like Mistral and Deepgram would for the made up tones.

    A speaker pass labels each voiced stretch by its pitch (low tone is one
    person, high tone the other). A side pass returns one piece of text per
    voiced stretch, named after where the stretch starts.
    """
    def post(url, params=None, headers=None, data=None, files=None, timeout=None):
        if "mistral" in url:
            if mistral_status != 200:
                return FakeResponse(mistral_status, None, text="Unauthorized")
            found = regions_of(files["file"].read())
            if data.get("diarize") == "true":
                segs = [segment("x", s, e, f"speaker_{n + 1}") for s, e, n in found]
            else:
                segs = [segment(f"at{s:.1f}", s, e) for s, e, _ in found]
            return FakeResponse(200, mistral_body(segs))
        found = regions_of(data)
        if params.get("diarize") == "true":
            words = [word("x", s, e, speaker=n) for s, e, n in found]
        else:
            words = [word(f"at{s:.1f}", s, e) for s, e, _ in found]
        return FakeResponse(200, deepgram_body(words))
    return post


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = diarize_meeting.main(argv)
    return code, out.getvalue(), err.getvalue()


def stage_result(backend="mistral", failures=None, turns=None):
    """What transcribe_stereo returns, for tests that skip the audio work."""
    turns = [{"speaker": "agent", "text": "Hello.", "start": 0.1, "end": 0.5, "language": "en"}] \
        if turns is None else turns
    return {"conversation": turns, "total_turns": len(turns), "backend": backend,
            "model": transcribe_sides.model_name_for(backend), "failures": failures or {},
            "audio_duration_seconds": 1.0, "chunking_used": False}


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.rec = os.path.join(self.dir, "meeting.wav")
        write_wav(self.rec, np.zeros(10, dtype=np.int16))
        which = mock.patch("shutil.which", return_value="/usr/bin/tool")
        which.start()
        self.addCleanup(which.stop)

    def test_no_key_at_all_stops_with_clear_message(self):
        patch_keys(self, mistral="", deepgram="")
        code, out, err = run_cli([self.rec])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error: Neither MISTRAL_API_KEY nor DEEPGRAM_API_KEY is set", err)

    def test_either_key_alone_is_enough(self):
        for keys in ({"mistral": "m"}, {"deepgram": "d"}):
            patch_keys(self, **keys)
            with mock.patch.object(prepare_meeting, "prepare_meeting_recording",
                                   return_value=("x.wav", {"backend": "mistral", "model": "m", "failures": {}})), \
                    mock.patch.object(transcribe_sides, "transcribe_stereo", return_value=stage_result()):
                code, _, err = run_cli([self.rec])
            self.assertEqual(code, 0, err)

    def test_fallback_is_reported_in_output_and_on_stderr(self):
        patch_keys(self, mistral="m", deepgram="d")
        speaker_info = {"backend": "deepgram", "model": "nova-2",
                        "failures": {"mistral": "Mistral diarization returned HTTP 401: x"}}
        result = stage_result("deepgram", {"mistral": "Mistral transcription returned HTTP 401: x"})
        with mock.patch.object(prepare_meeting, "prepare_meeting_recording", return_value=("x.wav", speaker_info)), \
                mock.patch.object(transcribe_sides, "transcribe_stereo", return_value=result):
            code, out, err = run_cli([self.rec])
        self.assertEqual(code, 0)
        output = json.loads(out)
        self.assertEqual(output["speaker_pass"]["backend"], "deepgram")
        self.assertTrue(output["speaker_pass"]["fell_back"])
        self.assertTrue(output["transcription"]["fell_back"])
        self.assertIn("warning: Finding the speakers: mistral failed", err)
        self.assertIn("warning: Transcription: mistral failed", err)
        self.assertIn("used deepgram instead", err)

    def test_no_fallback_no_warning(self):
        patch_keys(self, mistral="m", deepgram="d")
        with mock.patch.object(prepare_meeting, "prepare_meeting_recording",
                               return_value=("x.wav", {"backend": "mistral", "model": "m", "failures": {}})), \
                mock.patch.object(transcribe_sides, "transcribe_stereo", return_value=stage_result()):
            code, out, err = run_cli([self.rec])
        self.assertEqual(code, 0)
        self.assertNotIn("warning", err)
        self.assertFalse(json.loads(out)["transcription"]["fell_back"])

    def test_missing_recording_stops(self):
        patch_keys(self, mistral="m")
        code, _, err = run_cli([os.path.join(self.dir, "nope.wav")])
        self.assertEqual(code, 1)
        self.assertIn("Recording not found", err)

    def test_no_turns_is_an_error(self):
        patch_keys(self, mistral="m")
        with mock.patch.object(prepare_meeting, "prepare_meeting_recording",
                               return_value=("x.wav", {"backend": "mistral", "model": "m", "failures": {}})), \
                mock.patch.object(transcribe_sides, "transcribe_stereo", return_value=stage_result(turns=[])):
            code, _, err = run_cli([self.rec])
        self.assertEqual(code, 1)
        self.assertIn("no turns", err)

    def test_failure_inside_a_step_is_reported(self):
        patch_keys(self, mistral="m", deepgram="d")
        with mock.patch.object(prepare_meeting, "prepare_meeting_recording",
                               side_effect=MeetingDiarizationError("Finding the speakers failed: mistral: x; deepgram: y")):
            code, out, err = run_cli([self.rec])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error: Finding the speakers failed", err)


class AutomatedRunTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("CI"), "only checked in the automated test run")
    def test_end_to_end_is_not_skipped_in_the_automated_run(self):
        self.assertTrue(HAVE_FFMPEG, "the automated run must install ffmpeg and ffprobe")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg and ffprobe are not on the PATH")
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patch_keys(self, mistral="mistral-test-key-not-real", deepgram="test-key-not-real")
        rate = 16000
        silence = lambda s: np.zeros(int(s * rate), dtype=np.int16)
        low = lambda s: tone(s, rate, freq=300)
        high = lambda s: tone(s, rate, freq=1000)
        # Low voice opens, high voice answers, low voice again.
        audio = np.concatenate([
            silence(0.5), low(1.0), silence(0.5), high(1.0), silence(0.5), low(1.0), silence(0.5),
        ])
        self.rec = os.path.join(self.dir, "made_up_meeting.wav")
        write_wav(self.rec, audio, rate=rate)
        self.out_file = os.path.join(self.dir, "turns.json")

    def check_turns(self, result):
        turns = result["turns"]
        self.assertEqual([t["speaker"] for t in turns], ["agent", "customer", "agent"])
        self.assertEqual([t["text"] for t in turns], ["at0.5", "at2.0", "at3.5"])
        for t, expected in zip(turns, [0.5, 2.0, 3.5]):
            self.assertAlmostEqual(t["start"], expected, delta=0.05)
        self.assertAlmostEqual(result["audio_duration_seconds"], 5.0, delta=0.05)

    def test_three_turns_with_mistral(self):
        with mock.patch("requests.post", side_effect=fake_vendors()) as post:
            code, _, err = run_cli([self.rec, "--out", self.out_file])

        self.assertEqual(code, 0, err)
        self.assertEqual(post.call_count, 3)  # speaker pass once, then one call per side
        self.assertTrue(all("mistral" in c.args[0] for c in post.call_args_list))
        self.assertNotIn("warning", err)
        with open(self.out_file, encoding="utf-8") as f:
            result = json.load(f)
        self.check_turns(result)
        self.assertEqual(result["speaker_pass"]["backend"], "mistral")
        self.assertEqual(result["transcription"]["model"], "voxtral-mini-latest")

    def test_three_turns_when_mistral_fails_and_deepgram_takes_over(self):
        with mock.patch("requests.post", side_effect=fake_vendors(mistral_status=401)) as post:
            code, _, err = run_cli([self.rec, "--out", self.out_file])

        self.assertEqual(code, 0, err)
        vendors = ["mistral" if "mistral" in c.args[0] else "deepgram" for c in post.call_args_list]
        # Speaker pass: mistral fails, deepgram. Sides: mistral fails on the first side, deepgram does both.
        self.assertEqual(vendors, ["mistral", "deepgram", "mistral", "deepgram", "deepgram"])
        self.assertEqual(err.count("warning:"), 2)
        with open(self.out_file, encoding="utf-8") as f:
            result = json.load(f)
        self.check_turns(result)
        self.assertEqual(result["speaker_pass"]["backend"], "deepgram")
        self.assertEqual(result["transcription"]["backend"], "deepgram")
        self.assertIn("HTTP 401", result["transcription"]["failures"]["mistral"])


if __name__ == "__main__":
    unittest.main()
