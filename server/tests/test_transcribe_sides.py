"""Tests for transcribe_sides.py. Deepgram and ffmpeg are faked; nothing leaves the machine."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

import transcribe_sides
from errors import MeetingDiarizationError
from fakes import FakeResponse, deepgram_body, mistral_body, patch_keys, segment, word, write_wav


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patch_keys(self, mistral="mistral-test-key-not-real", deepgram="test-key-not-real")
        self.side = os.path.join(self.dir, "side.wav")
        write_wav(self.side, np.zeros(16000, dtype=np.int16), rate=16000)


class DeepgramSegmentsTests(Base):
    def test_words_grouped_by_gap(self):
        body = deepgram_body([
            word("Thanks", 0.2, 0.5),
            word("everyone.", 0.5, 1.0),
            word("Next", 2.5, 2.8),
            word("item.", 2.8, 3.1),
        ])
        with mock.patch("requests.post", return_value=FakeResponse(200, body)) as post:
            segs = transcribe_sides.transcribe_deepgram_segments(self.side, "agent", "en")

        self.assertEqual(segs, [
            {"speaker": "agent", "text": "Thanks everyone.", "start": 0.2, "end": 1.0, "language": "en"},
            {"speaker": "agent", "text": "Next item.", "start": 2.5, "end": 3.1, "language": "en"},
        ])
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["params"], {"punctuate": "true", "model": "nova-2"})
        self.assertNotIn("diarize", kwargs["params"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Token test-key-not-real")

    def test_falls_back_to_plain_word(self):
        w = word("Okay", 0.1, 0.3)
        del w["punctuated_word"]
        with mock.patch("requests.post", return_value=FakeResponse(200, deepgram_body([w]))):
            segs = transcribe_sides.transcribe_deepgram_segments(self.side, "customer", "en")
        self.assertEqual(segs[0]["text"], "okay")

    def test_silent_side_returns_nothing(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, deepgram_body([], transcript=""))):
            self.assertEqual(transcribe_sides.transcribe_deepgram_segments(self.side, "agent", "en"), [])

    def test_text_without_timings_stops(self):
        body = deepgram_body([], transcript="Some words")
        with mock.patch("requests.post", return_value=FakeResponse(200, body)):
            with self.assertRaisesRegex(MeetingDiarizationError, "without word timings"):
                transcribe_sides.transcribe_deepgram_segments(self.side, "agent", "en")

    def test_http_error_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(402, None, text="no credit")):
            with self.assertRaisesRegex(MeetingDiarizationError, "HTTP 402"):
                transcribe_sides.transcribe_deepgram_segments(self.side, "agent", "en")

    def test_missing_key_stops(self):
        with mock.patch.object(transcribe_sides, "DEEPGRAM_API_KEY", ""):
            with self.assertRaisesRegex(MeetingDiarizationError, "DEEPGRAM_API_KEY"):
                transcribe_sides.transcribe_deepgram_segments(self.side, "agent", "en")


class MergeTests(unittest.TestCase):
    def test_consolidate_orders_by_midpoint_and_merges_same_speaker(self):
        segs = [
            {"speaker": "agent", "text": "Welcome.", "start": 0.0, "end": 1.0, "language": "en"},
            {"speaker": "agent", "text": "Shall we start?", "start": 1.2, "end": 2.0, "language": "en"},
            {"speaker": "customer", "text": "Yes.", "start": 2.2, "end": 2.6, "language": "en"},
            {"speaker": "agent", "text": "Good.", "start": 3.0, "end": 3.4, "language": "en"},
        ]
        # Shuffle so the order comes from the midpoints, not from the input.
        out = transcribe_sides.consolidate_segments([segs[2], segs[3], segs[0], segs[1]])
        self.assertEqual([(t["speaker"], t["text"]) for t in out], [
            ("agent", "Welcome. Shall we start?"),
            ("customer", "Yes."),
            ("agent", "Good."),
        ])
        self.assertEqual(out[0]["end"], 2.0)
        self.assertNotIn("mid", out[0])

    def test_consolidate_empty(self):
        self.assertEqual(transcribe_sides.consolidate_segments([]), [])

    def test_deduplicate_drops_repeat_from_chunk_overlap(self):
        segs = [
            {"text": "end of chunk one", "start": 530.0, "end": 538.0},
            {"text": "end of chunk one", "start": 535.0, "end": 538.0},
            {"text": "start of chunk two", "start": 536.0, "end": 541.0},
        ]
        out = transcribe_sides.deduplicate_segments(segs)
        self.assertEqual([s["text"] for s in out], ["end of chunk one", "start of chunk two"])
        self.assertEqual(out[1]["start"], 538.0)


class ChunkingTests(Base):
    def test_duration_unreadable_stops(self):
        failed = subprocess.CompletedProcess([], 1, "", "Invalid data")
        with mock.patch("subprocess.run", return_value=failed):
            with self.assertRaisesRegex(MeetingDiarizationError, "Could not read the duration"):
                transcribe_sides.get_audio_duration(self.side)

    def test_chunk_extraction_failure_stops(self):
        with mock.patch.object(transcribe_sides, "get_audio_duration", return_value=1200.0), \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "bad")):
            with self.assertRaisesRegex(MeetingDiarizationError, "Failed to extract chunk 0"):
                transcribe_sides.split_audio_into_chunks(self.side)

    def test_too_many_chunks_stops(self):
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(transcribe_sides, "get_audio_duration", return_value=540.0 * 40), \
                mock.patch("subprocess.run", return_value=ok):
            with self.assertRaisesRegex(MeetingDiarizationError, "more than 20 chunks"):
                transcribe_sides.split_audio_into_chunks(self.side)

    def test_chunk_starts_overlap(self):
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(transcribe_sides, "get_audio_duration", return_value=1200.0), \
                mock.patch("subprocess.run", return_value=ok):
            chunks = transcribe_sides.split_audio_into_chunks(self.side)
        self.assertEqual([start for _, start in chunks], [0.0, 535.0, 1070.0])

    def test_long_side_offsets_chunk_times_and_stops_on_bad_chunk(self):
        chunks = [(self.side + ".chunk0.wav", 0.0), (self.side + ".chunk1.wav", 535.0)]
        replies = [
            [{"speaker": "agent", "text": "first", "start": 1.0, "end": 2.0, "language": "en"}],
            [{"speaker": "agent", "text": "second", "start": 10.0, "end": 11.0, "language": "en"}],
        ]
        with mock.patch.object(transcribe_sides, "get_audio_duration", return_value=1000.0), \
                mock.patch.object(transcribe_sides, "split_audio_into_chunks", return_value=chunks), \
                mock.patch.object(transcribe_sides, "transcribe_channel_direct", side_effect=replies):
            segs = transcribe_sides.transcribe_channel_chunked(self.side, "agent", "en", "mistral")
        self.assertEqual([(s["text"], s["start"]) for s in segs], [("first", 1.0), ("second", 545.0)])

        with mock.patch.object(transcribe_sides, "get_audio_duration", return_value=1000.0), \
                mock.patch.object(transcribe_sides, "split_audio_into_chunks", return_value=chunks), \
                mock.patch.object(transcribe_sides, "transcribe_channel_direct",
                                  side_effect=[replies[0], MeetingDiarizationError("chunk failed")]):
            with self.assertRaisesRegex(MeetingDiarizationError, "chunk failed"):
                transcribe_sides.transcribe_channel_chunked(self.side, "agent", "en", "mistral")


class MistralSegmentsTests(Base):
    def test_request_and_parse(self):
        body = mistral_body([segment(" Thanks everyone. ", 0.2, 1.0), segment("Next item.", 2.5, 3.1)])
        with mock.patch("requests.post", return_value=FakeResponse(200, body)) as post:
            segs = transcribe_sides.transcribe_channel_direct(self.side, "agent", "en", "mistral")
        self.assertEqual(segs, [
            {"speaker": "agent", "text": "Thanks everyone.", "start": 0.2, "end": 1.0, "language": "en"},
            {"speaker": "agent", "text": "Next item.", "start": 2.5, "end": 3.1, "language": "en"},
        ])
        self.assertEqual(post.call_args.args[0], "https://api.mistral.ai/v1/audio/transcriptions")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer mistral-test-key-not-real")
        self.assertEqual(kwargs["data"], {"model": "voxtral-mini-latest", "timestamp_granularities": ["segment"]})
        self.assertNotIn("diarize", kwargs["data"])

    def test_silent_side_returns_nothing(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, mistral_body([], text=""))):
            self.assertEqual(transcribe_sides.transcribe_channel_direct(self.side, "agent", "en", "mistral"), [])

    def test_text_without_segments_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, mistral_body([], text="Some words"))):
            with self.assertRaisesRegex(MeetingDiarizationError, "without segment timings"):
                transcribe_sides.transcribe_channel_direct(self.side, "agent", "en", "mistral")

    def test_missing_key_stops(self):
        patch_keys(self, mistral="", deepgram="test-key-not-real")
        with self.assertRaisesRegex(MeetingDiarizationError, "MISTRAL_API_KEY"):
            transcribe_sides.transcribe_channel_direct(self.side, "agent", "en", "mistral")


def stereo_fakes(case):
    """A made up two sided file, a fake ffmpeg and a fixed duration."""
    stereo = os.path.join(case.dir, "meeting.synthetic.wav")
    write_wav(stereo, np.zeros(16000, dtype=np.int16), rate=8000, channels=2)

    def fake_ffmpeg(cmd, **kwargs):
        write_wav(cmd[-1], np.zeros(16000, dtype=np.int16), rate=16000)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    run = mock.patch("subprocess.run", side_effect=fake_ffmpeg)
    duration = mock.patch.object(transcribe_sides, "get_audio_duration", return_value=4.0)
    return stereo, run, duration


MISTRAL_LEFT = mistral_body([segment("Welcome", 0.2, 0.6), segment("Shall we?", 3.0, 3.4)])
MISTRAL_RIGHT = mistral_body([segment("Thanks.", 1.0, 1.4)])
DEEPGRAM_LEFT = deepgram_body([word("Welcome", 0.2, 0.6), word("Shall", 3.0, 3.2), word("we?", 3.2, 3.4)])
DEEPGRAM_RIGHT = deepgram_body([word("Thanks.", 1.0, 1.4)])
EXPECTED_TURNS = [("agent", "Welcome"), ("customer", "Thanks."), ("agent", "Shall we?")]


class TranscribeStereoTests(Base):
    def test_mistral_by_default_left_is_agent_right_is_customer(self):
        stereo, run_patch, duration_patch = stereo_fakes(self)
        replies = [FakeResponse(200, MISTRAL_LEFT), FakeResponse(200, MISTRAL_RIGHT)]
        with run_patch as run, duration_patch, mock.patch("requests.post", side_effect=replies) as post:
            result = transcribe_sides.transcribe_stereo(stereo)

        self.assertTrue(all("mistral" in c.args[0] for c in post.call_args_list))
        pans = [c.args[0][c.args[0].index("-af") + 1] for c in run.call_args_list]
        self.assertEqual(pans, ["pan=mono|c0=c0", "pan=mono|c0=c1"])
        self.assertEqual([(t["speaker"], t["text"]) for t in result["conversation"]], EXPECTED_TURNS)
        self.assertEqual(result["backend"], "mistral")
        self.assertEqual(result["model"], "voxtral-mini-latest")
        self.assertEqual(result["failures"], {})
        self.assertEqual(result["total_turns"], 3)
        self.assertFalse(result["chunking_used"])
        self.assertFalse(os.path.exists(stereo + ".left.wav"))
        self.assertFalse(os.path.exists(stereo + ".right.wav"))

    def test_failure_on_one_side_moves_both_sides_to_deepgram(self):
        stereo, run_patch, duration_patch = stereo_fakes(self)
        replies = [
            FakeResponse(200, MISTRAL_LEFT),               # mistral, agent side: fine
            FakeResponse(503, None, text="unavailable"),  # mistral, customer side: fails
            FakeResponse(200, DEEPGRAM_LEFT),             # deepgram redoes the agent side
            FakeResponse(200, DEEPGRAM_RIGHT),            # and the customer side
        ]
        with run_patch, duration_patch, mock.patch("requests.post", side_effect=replies) as post:
            result = transcribe_sides.transcribe_stereo(stereo)

        vendors = ["mistral" if "mistral" in c.args[0] else "deepgram" for c in post.call_args_list]
        self.assertEqual(vendors, ["mistral", "mistral", "deepgram", "deepgram"])
        self.assertEqual(result["backend"], "deepgram")
        self.assertEqual(result["model"], "nova-2")
        self.assertIn("HTTP 503", result["failures"]["mistral"])
        self.assertEqual([(t["speaker"], t["text"]) for t in result["conversation"]], EXPECTED_TURNS)

    def test_deepgram_only_reader(self):
        patch_keys(self, mistral="", deepgram="test-key-not-real")
        stereo, run_patch, duration_patch = stereo_fakes(self)
        replies = [FakeResponse(200, DEEPGRAM_LEFT), FakeResponse(200, DEEPGRAM_RIGHT)]
        with run_patch, duration_patch, mock.patch("requests.post", side_effect=replies) as post:
            result = transcribe_sides.transcribe_stereo(stereo)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["backend"], "deepgram")
        self.assertIn("not configured", result["failures"]["mistral"])

    def test_both_fail_stops(self):
        stereo, run_patch, duration_patch = stereo_fakes(self)
        replies = [FakeResponse(401, None, text="Unauthorized"), FakeResponse(402, None, text="no credit")]
        with run_patch, duration_patch, mock.patch("requests.post", side_effect=replies):
            with self.assertRaisesRegex(MeetingDiarizationError,
                                        "every backend: mistral: .*HTTP 401.*deepgram: .*HTTP 402"):
                transcribe_sides.transcribe_stereo(stereo)
        self.assertFalse(os.path.exists(stereo + ".left.wav"))

    def test_channel_extraction_failure_stops(self):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "bad")):
            with self.assertRaisesRegex(MeetingDiarizationError, "Left channel extraction failed"):
                transcribe_sides.transcribe_stereo(self.side)


if __name__ == "__main__":
    unittest.main()
