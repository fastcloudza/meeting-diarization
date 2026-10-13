# Copyright (c) 2026 Arno Hart. All rights reserved.
# Published for viewing only. No licence is granted. See LICENSE.
"""Tests for prepare_meeting.py. Deepgram and ffmpeg are faked; nothing leaves the machine."""
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
from fakes import FakeResponse, deepgram_body, read_wav, word, write_wav


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        patcher = mock.patch.object(prepare_meeting, "DEEPGRAM_API_KEY", "test-key-not-real")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mono = os.path.join(self.dir, "mono.wav")
        write_wav(self.mono, np.zeros(8000, dtype=np.int16))


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
        body = deepgram_body([word("Hi", 0.1, 0.5, speaker=0), word("Hello", 1.0, 1.5, speaker=1)])
        with mock.patch("subprocess.run", side_effect=self.fake_ffmpeg()) as run, \
                mock.patch("requests.post", return_value=FakeResponse(200, body)):
            out = prepare_meeting.prepare_meeting_recording(self.recording, self.dir)

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:4], ["ffmpeg", "-y", "-i", self.recording])
        self.assertIn("8000", cmd)
        self.assertTrue(out.endswith(".synthetic.wav"))
        self.assertEqual(read_wav(out)[1], 2)
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
        with mock.patch("subprocess.run", side_effect=self.fake_ffmpeg()), \
                mock.patch("requests.post", return_value=FakeResponse(500, None, text="busy")):
            with self.assertRaisesRegex(MeetingDiarizationError, "HTTP 500"):
                prepare_meeting.prepare_meeting_recording(self.recording, self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "meeting.m4a.mono8k.wav")))


if __name__ == "__main__":
    unittest.main()
