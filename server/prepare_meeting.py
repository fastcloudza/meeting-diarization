"""
Meeting preparation: one recording of a meeting becomes a two sided file.

The recording is downmixed to 8 kHz mono, Deepgram finds who speaks when, and
the audio is rebuilt as stereo: the first person heard goes on the left
channel, everyone else on the right. That file then goes through the same per
side transcription as a two channel phone call (see transcribe_sides.py).
"""
import os
import wave
import logging
import subprocess

import numpy as np
import requests

from errors import MeetingDiarizationError

# Deepgram settings come from the environment. The key is never written in a file.
DEEPGRAM_API_URL = os.environ.get("DEEPGRAM_API_URL", "https://api.deepgram.com/v1/listen")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
DEEPGRAM_MODEL = os.environ.get("DEEPGRAM_MODEL", "nova-2")


def deepgram_diarise(mono_wav_path):
    """Call Deepgram with diarize=true. Return a list of segments.
    Each segment is {speaker_id (str, e.g. "speaker_1"), start (float), end (float)}.
    Deepgram's transcript text is discarded here; only word level timestamps and
    speaker labels are used. Deepgram authenticates with `Authorization: Token <key>`
    (not Bearer) and takes the raw WAV bytes as the request body (not a multipart
    file upload).
    Raises MeetingDiarizationError on any failure.
    """
    if not DEEPGRAM_API_URL or not DEEPGRAM_API_KEY:
        raise MeetingDiarizationError(
            "Deepgram is not configured: set DEEPGRAM_API_KEY in the environment"
        )
    with open(mono_wav_path, "rb") as f:
        audio_bytes = f.read()
    try:
        resp = requests.post(
            DEEPGRAM_API_URL,
            params={"diarize": "true", "punctuate": "true", "model": DEEPGRAM_MODEL},
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "audio/wav",
            },
            data=audio_bytes,
            timeout=300,
        )
    except requests.exceptions.RequestException as e:
        raise MeetingDiarizationError(f"Deepgram diarization request failed: {e}") from e
    if resp.status_code != 200:
        raise MeetingDiarizationError(
            f"Deepgram diarization returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    try:
        result = resp.json()
        words = result["results"]["channels"][0]["alternatives"][0]["words"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise MeetingDiarizationError(
            f"Deepgram diarization response did not have the expected shape: {e!r}"
        ) from e

    # Group consecutive same speaker words into segments. speaker is a 0 based int from
    # Deepgram; +1 gives speaker_1 / speaker_2 naming.
    segments = []
    current = None
    for w in words:
        s = w.get("speaker")
        if not isinstance(s, int):
            raise MeetingDiarizationError(
                "Deepgram returned words without a speaker label, so diarization was not applied"
            )
        if current is None or s != current["speaker_int"]:
            if current:
                segments.append({
                    "start": current["start"],
                    "end": current["end"],
                    "speaker_id": f"speaker_{current['speaker_int'] + 1}",
                })
            current = {"speaker_int": s, "start": w["start"], "end": w["end"]}
        else:
            current["end"] = w["end"]
    if current:
        segments.append({
            "start": current["start"],
            "end": current["end"],
            "speaker_id": f"speaker_{current['speaker_int'] + 1}",
        })

    if not segments:
        raise MeetingDiarizationError("Deepgram diarization found no speech in the recording")
    speakers = {seg["speaker_id"] for seg in segments}
    logging.info(f"[DIARISE] Deepgram diarisation: {len(segments)} segments, {len(speakers)} speakers")
    return segments


def build_synthetic_stereo(mono_wav_path, segments, output_path):
    """Build a stereo WAV from a mono source using diarised segments.
    First seen speaker_id (by start timestamp) goes to the L channel; all others to the R channel.
    Silence elsewhere on each channel. Original timing preserved exactly.
    """
    with wave.open(mono_wav_path, "rb") as w:
        sr = w.getframerate()
        sample_width = w.getsampwidth()
        n_frames = w.getnframes()
        mono = np.frombuffer(w.readframes(n_frames), dtype=np.int16)

    sorted_segs = sorted(segments, key=lambda s: s.get("start", 0.0))
    if not sorted_segs:
        raise ValueError("No segments to build synthetic stereo from")
    first_speaker = sorted_segs[0].get("speaker_id")

    L = np.zeros_like(mono)
    R = np.zeros_like(mono)
    l_segs = r_segs = 0
    for seg in sorted_segs:
        a = int(seg.get("start", 0.0) * sr)
        b = min(int(seg.get("end", 0.0) * sr), len(mono))
        if b <= a:
            continue
        if seg.get("speaker_id") == first_speaker:
            L[a:b] = mono[a:b]
            l_segs += 1
        else:
            R[a:b] = mono[a:b]
            r_segs += 1

    stereo = np.empty(2 * len(mono), dtype=np.int16)
    stereo[0::2] = L
    stereo[1::2] = R

    with wave.open(output_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(sample_width)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())

    logging.info(f"[DIARISE] Synthetic stereo: L={first_speaker} ({l_segs} segs), R=others ({r_segs} segs)")


def prepare_meeting_recording(recording_file, work_dir):
    """Diarise a meeting recording and rebuild it as two sided stereo.
    Returns the path to the new stereo WAV in work_dir, ready for
    transcribe_sides.transcribe_stereo.
    Raises MeetingDiarizationError if any step fails.
    """
    logging.info(f"[DIARISE] Meeting recording: {recording_file}")
    base = os.path.basename(recording_file)
    mono_path = os.path.join(work_dir, f"{base}.mono8k.wav")
    synth_path = os.path.join(work_dir, f"{base}.synthetic.wav")

    try:
        # Single ffmpeg pass: 8kHz mono. The same rate is reused for the
        # synthetic stereo output, the same shape as a two channel phone recording.
        try:
            result = subprocess.run([
                "ffmpeg", "-y", "-i", recording_file,
                "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le",
                mono_path,
            ], capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            raise MeetingDiarizationError("ffmpeg was not found on the PATH") from e
        except subprocess.TimeoutExpired as e:
            raise MeetingDiarizationError("ffmpeg downmix took longer than 120 seconds") from e
        if result.returncode != 0:
            raise MeetingDiarizationError(f"ffmpeg downmix failed: {result.stderr[-500:]}")

        segments = deepgram_diarise(mono_path)
        build_synthetic_stereo(mono_path, segments, synth_path)
        return synth_path
    finally:
        if os.path.exists(mono_path):
            try:
                os.remove(mono_path)
            except Exception:
                pass
