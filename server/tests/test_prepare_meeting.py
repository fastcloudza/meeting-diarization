"""Tests for prepare_meeting.py. Mistral, Deepgram and ffmpeg are faked; nothing leaves the machine."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np
import requests

import prepare_meeting
from errors import MeetingDiarizationError
from fakes import (FakeResponse, deepgram_body, mistral_body, patch_keys, read_wav,
                   segment, word, write_wav)

MISTRAL_URL = "https://api.mistral.ai/v1/audio/transcriptions"


def by_vendor(mistral=None, deepgram=None):
    """A fake requests.post that answers by which vendor's URL was called."""
    def post(url, **kwargs):
        reply = mistral if "mistral" in url else deepgram
        if reply is None:
            raise AssertionError(f"unexpected request to {url}")
        if isinstance(reply, Exception):
            raise reply
        return reply
    return post


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patch_keys(self, mistral="mistral-test-key-not-real", deepgram="test-key-not-real")
        self.mono = os.path.join(self.dir, "mono.wav")
        write_wav(self.mono, np.zeros(8000, dtype=np.int16))


TWO_SPEAKERS_MISTRAL = mistral_body([
    segment("Good morning.", 0.5, 1.2, "speaker_1"),
    segment("Hi there.", 1.5, 2.0, "speaker_2"),
])
TWO_SPEAKERS_DEEPGRAM = deepgram_body([
    word("Good", 0.5, 0.8, speaker=0),
    word("Hi", 1.5, 1.7, speaker=1),
])


class MistralDiariseTests(Base):
    def test_request_and_segments(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, TWO_SPEAKERS_MISTRAL)) as post:
            segments = prepare_meeting.mistral_diarise(self.mono)

        self.assertEqual([s["speaker_id"] for s in segments], ["speaker_1", "speaker_2"])
        self.assertEqual(post.call_args.args[0], MISTRAL_URL)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer mistral-test-key-not-real")
        self.assertEqual(kwargs["data"], {
            "model": "voxtral-mini-latest",
            "diarize": "true",
            "timestamp_granularities": ["segment"],
        })
        self.assertIn("file", kwargs["files"])

    def test_missing_key_stops(self):
        with mock.patch.object(prepare_meeting, "MISTRAL_API_KEY", ""):
            with self.assertRaisesRegex(MeetingDiarizationError, "MISTRAL_API_KEY"):
                prepare_meeting.mistral_diarise(self.mono)

    def test_http_error_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(401, None, text="Unauthorized")):
            with self.assertRaisesRegex(MeetingDiarizationError, "Mistral diarization returned HTTP 401"):
                prepare_meeting.mistral_diarise(self.mono)

    def test_no_segments_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, mistral_body([], text=""))):
            with self.assertRaisesRegex(MeetingDiarizationError, "no segments"):
                prepare_meeting.mistral_diarise(self.mono)

    def test_segments_without_speaker_stop(self):
        body = mistral_body([segment("Hello.", 0.1, 0.5)])
        with mock.patch("requests.post", return_value=FakeResponse(200, body)):
            with self.assertRaisesRegex(MeetingDiarizationError, "without a speaker label"):
                prepare_meeting.mistral_diarise(self.mono)


class FindSpeakersOrderTests(Base):
    def test_mistral_first_and_deepgram_untouched(self):
        fake = by_vendor(mistral=FakeResponse(200, TWO_SPEAKERS_MISTRAL))
        with mock.patch("requests.post", side_effect=fake) as post:
            segments, info = prepare_meeting.find_speakers(self.mono)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(info, {"backend": "mistral", "model": "voxtral-mini-latest", "failures": {}})
        self.assertEqual(len(segments), 2)

    def test_deepgram_takes_over_when_mistral_fails(self):
        fake = by_vendor(mistral=FakeResponse(401, None, text="Unauthorized"),
                         deepgram=FakeResponse(200, TWO_SPEAKERS_DEEPGRAM))
        with mock.patch("requests.post", side_effect=fake) as post:
            segments, info = prepare_meeting.find_speakers(self.mono)
        self.assertEqual(post.call_count, 2)
        self.assertIn("mistral", post.call_args_list[0].args[0])
        self.assertIn("deepgram", post.call_args_list[1].args[0])
        self.assertEqual(info["backend"], "deepgram")
        self.assertIn("HTTP 401", info["failures"]["mistral"])
        self.assertEqual([s["speaker_id"] for s in segments], ["speaker_1", "speaker_2"])

    def test_deepgram_takes_over_on_network_error(self):
        fake = by_vendor(mistral=requests.exceptions.Timeout("slow"),
                         deepgram=FakeResponse(200, TWO_SPEAKERS_DEEPGRAM))
        with mock.patch("requests.post", side_effect=fake):
            _, info = prepare_meeting.find_speakers(self.mono)
        self.assertEqual(info["backend"], "deepgram")
        self.assertIn("request failed", info["failures"]["mistral"])

    def test_deepgram_only_reader_skips_mistral_and_says_so(self):
        patch_keys(self, mistral="", deepgram="test-key-not-real")
        fake = by_vendor(deepgram=FakeResponse(200, TWO_SPEAKERS_DEEPGRAM))
        with mock.patch("requests.post", side_effect=fake) as post:
            _, info = prepare_meeting.find_speakers(self.mono)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(info["backend"], "deepgram")
        self.assertIn("not configured", info["failures"]["mistral"])

    def test_mistral_fails_and_no_backup_key_stops(self):
        patch_keys(self, mistral="mistral-test-key-not-real", deepgram="")
        fake = by_vendor(mistral=FakeResponse(500, None, text="busy"))
        with mock.patch("requests.post", side_effect=fake) as post:
            with self.assertRaisesRegex(MeetingDiarizationError, "mistral: .*HTTP 500.*deepgram: not configured"):
                prepare_meeting.find_speakers(self.mono)
        self.assertEqual(post.call_count, 1)

    def test_both_fail_stops(self):
        fake = by_vendor(mistral=FakeResponse(401, None, text="Unauthorized"),
                         deepgram=FakeResponse(402, None, text="no credit"))
        with mock.patch("requests.post", side_effect=fake):
            with self.assertRaisesRegex(MeetingDiarizationError, "mistral: .*HTTP 401.*deepgram: .*HTTP 402"):
                prepare_meeting.find_speakers(self.mono)


class DeepgramDiariseTests(Base):
    def test_groups_words_into_speaker_segments(self):
        body = deepgram_body([
            word("Good", 0.5, 0.8, speaker=0),
            word("morning.", 0.8, 1.2, speaker=0),
            word("Hi", 1.5, 1.7, speaker=1),
            word("there.", 1.7, 2.0, speaker=1),
            word("Shall", 2.4, 2.6, speaker=0),
            word("we", 2.6, 2.7, speaker=2),
        ])
        with mock.patch("requests.post", return_value=FakeResponse(200, body)) as post:
            segments = prepare_meeting.deepgram_diarise(self.mono)

        self.assertEqual(segments, [
            {"start": 0.5, "end": 1.2, "speaker_id": "speaker_1"},
            {"start": 1.5, "end": 2.0, "speaker_id": "speaker_2"},
            {"start": 2.4, "end": 2.6, "speaker_id": "speaker_1"},
            {"start": 2.6, "end": 2.7, "speaker_id": "speaker_3"},
        ])
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["params"], {"diarize": "true", "punctuate": "true", "model": "nova-2"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Token test-key-not-real")
        self.assertEqual(kwargs["headers"]["Content-Type"], "audio/wav")
        with open(self.mono, "rb") as f:
            self.assertEqual(kwargs["data"], f.read())

    def test_missing_key_stops(self):
        with mock.patch.object(prepare_meeting, "DEEPGRAM_API_KEY", ""):
            with self.assertRaisesRegex(MeetingDiarizationError, "DEEPGRAM_API_KEY"):
                prepare_meeting.deepgram_diarise(self.mono)

    def test_http_error_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(401, None, text="Invalid credentials")):
            with self.assertRaisesRegex(MeetingDiarizationError, "HTTP 401"):
                prepare_meeting.deepgram_diarise(self.mono)

    def test_network_error_stops(self):
        with mock.patch("requests.post", side_effect=requests.exceptions.ConnectionError("down")):
            with self.assertRaisesRegex(MeetingDiarizationError, "request failed"):
                prepare_meeting.deepgram_diarise(self.mono)

    def test_unexpected_shape_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, {"results": {}})):
            with self.assertRaisesRegex(MeetingDiarizationError, "expected shape"):
                prepare_meeting.deepgram_diarise(self.mono)

    def test_words_without_speaker_stop(self):
        body = deepgram_body([word("Hello", 0.1, 0.4)])
        with mock.patch("requests.post", return_value=FakeResponse(200, body)):
            with self.assertRaisesRegex(MeetingDiarizationError, "without a speaker label"):
                prepare_meeting.deepgram_diarise(self.mono)

    def test_no_speech_stops(self):
        with mock.patch("requests.post", return_value=FakeResponse(200, deepgram_body([]))):
            with self.assertRaisesRegex(MeetingDiarizationError, "no speech"):
                prepare_meeting.deepgram_diarise(self.mono)


class BuildSyntheticStereoTests(Base):
    def test_first_speaker_left_everyone_else_right(self):
        rate = 8000
        mono = np.arange(1, 4 * rate + 1, dtype=np.int64) % 30000 + 1
        write_wav(self.mono, mono, rate=rate)
        out = os.path.join(self.dir, "stereo.wav")
        # Given out of order on purpose: the first speaker is chosen by start time.
        segments = [
            {"start": 2.0, "end": 3.0, "speaker_id": "speaker_2"},
            {"start": 0.5, "end": 1.5, "speaker_id": "speaker_1"},
            {"start": 3.0, "end": 3.5, "speaker_id": "speaker_3"},
        ]
        prepare_meeting.build_synthetic_stereo(self.mono, segments, out)

        out_rate, channels, data = read_wav(out)
        self.assertEqual((out_rate, channels), (rate, 2))
        left, right = data[0::2], data[1::2]
        src = mono.astype(np.int16)
        self.assertEqual(len(left), len(src))

        def sl(a, b):
            return slice(int(a * rate), int(b * rate))

        np.testing.assert_array_equal(left[sl(0.5, 1.5)], src[sl(0.5, 1.5)])
        np.testing.assert_array_equal(right[sl(2.0, 3.5)], src[sl(2.0, 3.5)])
        self.assertFalse(left[sl(2.0, 4.0)].any())
        self.assertFalse(right[sl(0.0, 2.0)].any())
        self.assertFalse(left[sl(0.0, 0.5)].any())
        self.assertFalse(right[sl(3.5, 4.0)].any())

    def test_segment_past_end_is_clipped(self):
        write_wav(self.mono, np.ones(8000, dtype=np.int16), rate=8000)
        out = os.path.join(self.dir, "stereo.wav")
        prepare_meeting.build_synthetic_stereo(
            self.mono, [{"start": 0.5, "end": 9.0, "speaker_id": "speaker_1"}], out
        )
        _, _, data = read_wav(out)
        self.assertEqual(len(data), 16000)

    def test_no_segments_raises(self):
        with self.assertRaises(ValueError):
            prepare_meeting.build_synthetic_stereo(self.mono, [], os.path.join(self.dir, "x.wav"))


class PrepareMeetingRecordingTests(Base):
    def setUp(self):
        super().setUp()
        self.recording = os.path.join(self.dir, "meeting.m4a")
        with open(self.recording, "wb") as f:
            f.write(b"not real audio")

    def fake_ffmpeg(self, returncode=0):
        def run(cmd, **kwargs):
            if returncode == 0:
                write_wav(cmd[-1], np.ones(16000, dtype=np.int16), rate=8000)
            return subprocess.CompletedProcess(cmd, returncode, "", "ffmpeg said no")
        return run

    def test_builds_two_sided_file_and_removes_mono(self):
        fake = by_vendor(mistral=FakeResponse(200, TWO_SPEAKERS_MISTRAL))
        with mock.patch("subprocess.run", side_effect=self.fake_ffmpeg()) as run, \
                mock.patch("requests.post", side_effect=fake):
            out, info = prepare_meeting.prepare_meeting_recording(self.recording, self.dir)

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:4], ["ffmpeg", "-y", "-i", self.recording])
        self.assertIn("8000", cmd)
        self.assertTrue(out.endswith(".synthetic.wav"))
        self.assertEqual(read_wav(out)[1], 2)
        self.assertEqual(info["backend"], "mistral")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "meeting.m4a.mono8k.wav")))

    def test_ffmpeg_failure_stops(self):
        with mock.patch("subprocess.run", side_effect=self.fake_ffmpeg(returncode=1)):
            with self.assertRaisesRegex(MeetingDiarizationError, "downmix failed"):
                prepare_meeting.prepare_meeting_recording(self.recording, self.dir)

    def test_ffmpeg_missing_stops(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg")):
            with self.assertRaisesRegex(MeetingDiarizationError, "ffmpeg was not found"):
                prepare_meeting.prepare_meeting_recording(self.recording, self.dir)

    def test_diarization_failure_stops_and_cleans_up(self):
        fake = by_vendor(mistral=FakeResponse(500, None, text="busy"),
                         deepgram=FakeResponse(500, None, text="busy"))
        with mock.patch("subprocess.run", side_effect=self.fake_ffmpeg()), \
                mock.patch("requests.post", side_effect=fake):
            with self.assertRaisesRegex(MeetingDiarizationError, "HTTP 500"):
                prepare_meeting.prepare_meeting_recording(self.recording, self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "meeting.m4a.mono8k.wav")))


if __name__ == "__main__":
    unittest.main()
