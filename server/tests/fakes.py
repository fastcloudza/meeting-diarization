"""Made up test data in the shape Deepgram returns. Nothing here is a real recording."""
import json
import wave

import numpy as np


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
