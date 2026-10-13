"""Made up test data in the shapes Mistral and Deepgram return. Nothing here is a real recording."""
import json
import wave
from unittest import mock

import numpy as np

import prepare_meeting
import transcribe_sides


def patch_keys(case, mistral="", deepgram=""):
    """Fix both keys in both modules for one test, whatever the environment holds.

    An empty string means that backend is not configured. Tests never see a real key.
    """
    for mod in (prepare_meeting, transcribe_sides):
        for name, value in (("MISTRAL_API_KEY", mistral), ("DEEPGRAM_API_KEY", deepgram)):
            patcher = mock.patch.object(mod, name, value)
            patcher.start()
            case.addCleanup(patcher.stop)


def segment(text, start, end, speaker_id=None):
    """One entry of a Mistral transcription response's segments."""
    s = {"text": text, "start": start, "end": end, "type": "transcription_segment"}
    if speaker_id is not None:
        s["speaker_id"] = speaker_id
    return s


def mistral_body(segments, text=None):
    """A /v1/audio/transcriptions response body around the given segments."""
    if text is None:
        text = " ".join(s.get("text", "") for s in segments)
    return {
        "model": "voxtral-mini-latest",
        "text": text,
        "language": None,
        "segments": segments,
        "usage": {"prompt_audio_seconds": 10, "prompt_tokens": 0, "total_tokens": 0, "completion_tokens": 0},
    }


class FakeResponse:
    """Stands in for requests.Response."""

    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)
        self.reason = "OK" if status_code == 200 else "Error"

    def json(self):
        if self._body is None:
            raise ValueError("No JSON body")
        return self._body


def word(text, start, end, speaker=None):
    """One entry of results.channels[0].alternatives[0].words."""
    w = {"word": text.lower().strip(".,?!"), "start": start, "end": end, "confidence": 0.99}
    if speaker is not None:
        w["speaker"] = speaker
        w["speaker_confidence"] = 0.9
    w["punctuated_word"] = text
    return w


def deepgram_body(words, transcript=None):
    """A prerecorded /v1/listen response body around the given words."""
    if transcript is None:
        transcript = " ".join(w.get("punctuated_word") or w["word"] for w in words)
    return {
        "metadata": {"request_id": "00000000-0000-0000-0000-000000000000", "channels": 1},
        "results": {
            "channels": [
                {"alternatives": [{"transcript": transcript, "confidence": 0.99, "words": words}]}
            ]
        },
    }


def write_wav(path, samples, rate=8000, channels=1):
    """Write int16 samples to a WAV file."""
    data = np.asarray(samples, dtype=np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def read_wav(path):
    """Return (rate, channels, int16 samples) from a WAV file."""
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return rate, channels, data


def tone(seconds, rate, freq=440.0, amplitude=8000):
    """A sine tone standing in for a voice."""
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)
