"""
Per side transcription of a two sided recording.

Left channel = agent, right channel = customer. Each channel is split out with
ffmpeg, transcribed on its own with Deepgram, and the two sides are merged back
into one conversation ordered by time. Long audio is cut into overlapping
chunks and the overlap is removed again on reassembly.
"""
import os
import json
import logging
import subprocess

import requests

from errors import MeetingDiarizationError

# Deepgram settings come from the environment. The key is never written in a file.
DEEPGRAM_API_URL = os.environ.get("DEEPGRAM_API_URL", "https://api.deepgram.com/v1/listen")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
DEEPGRAM_MODEL = os.environ.get("DEEPGRAM_MODEL", "nova-2")

# Chunking configuration
CHUNK_DURATION = 540       # 9 minutes in seconds
CHUNK_OVERLAP = 5          # 5 second overlap to avoid cut words
MAX_DIRECT_DURATION = 540  # Files under 9 min are sent whole
MAX_CHUNKS = 20            # Safety limit on the chunk loop


def get_audio_duration(audio_path):
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path
        ], capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise MeetingDiarizationError("ffprobe was not found on the PATH") from e
    except subprocess.TimeoutExpired as e:
        raise MeetingDiarizationError(f"ffprobe timed out reading {audio_path}") from e

    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            pass
    raise MeetingDiarizationError(
        f"Could not read the duration of {audio_path}: {result.stderr.strip()[-300:]}"
    )


def split_audio_into_chunks(audio_path, chunk_duration=CHUNK_DURATION, overlap=CHUNK_OVERLAP):
    """
    Split audio file into chunks with overlap.
    Returns list of (chunk_path, start_time) tuples.
    """
    duration = get_audio_duration(audio_path)
    if duration <= 0:
        raise MeetingDiarizationError(f"Audio has no duration: {audio_path}")

    chunks = []
    start_time = 0.0
    chunk_index = 0

    while start_time < duration:
        if chunk_index >= MAX_CHUNKS:
            raise MeetingDiarizationError(
                f"Recording needs more than {MAX_CHUNKS} chunks; it is too long for this method"
            )
        chunk_path = f"{audio_path}.chunk{chunk_index}.wav"

        # Calculate chunk end time
        end_time = min(start_time + chunk_duration, duration)
        chunk_length = end_time - start_time

        # Extract chunk using ffmpeg
        result = subprocess.run([
            'ffmpeg', '-y',
            '-i', audio_path,
            '-ss', str(start_time),
            '-t', str(chunk_length),
            '-ar', '16000',
            '-ac', '1',
            '-c:a', 'pcm_s16le',
            chunk_path
        ], capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise MeetingDiarizationError(
                f"Failed to extract chunk {chunk_index}: {result.stderr[-500:]}"
            )

        chunks.append((chunk_path, start_time))
        logging.info(f"[CHUNK] Created chunk {chunk_index}: {start_time:.1f}s to {end_time:.1f}s")

        # Move to next chunk with overlap
        start_time += chunk_duration - overlap
        chunk_index += 1

    return chunks


def deduplicate_segments(segments, overlap=CHUNK_OVERLAP):
    """
    Remove duplicate text from overlapping chunk boundaries.
    Uses timestamp based deduplication.
    """
    if len(segments) <= 1:
        return segments

    # Sort by start time
    segments.sort(key=lambda x: x['start'])

    deduplicated = [segments[0]]

    for seg in segments[1:]:
        prev = deduplicated[-1]

        # Check for significant overlap
        if seg['start'] < prev['end'] - 1:
            # Segments overlap: check if same/similar text
            if seg['text'].strip() == prev['text'].strip():
                # Exact duplicate: skip
                continue
            elif seg['start'] < prev['end']:
                # Partial overlap: adjust start time
                seg['start'] = prev['end']

        deduplicated.append(seg)

    return deduplicated


def _deepgram_alternative(audio_path, extra_params=None):
    """POST audio to Deepgram and return the first channel's first alternative.

    Raises MeetingDiarizationError on misconfiguration, a failed request,
    a non 200 status or a malformed response.
    """
    if not DEEPGRAM_API_KEY:
        raise MeetingDiarizationError(
            "Deepgram is not configured: set DEEPGRAM_API_KEY in the environment"
        )
    if not DEEPGRAM_API_URL:
        raise MeetingDiarizationError("Deepgram API URL is not configured")

    params = {"punctuate": "true", "model": DEEPGRAM_MODEL}
    if extra_params:
        params.update(extra_params)
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",  # Deepgram uses `Token`, not `Bearer`
        "Content-Type": "audio/wav",
    }

    with open(audio_path, "rb") as audio_file:
        audio_bytes = audio_file.read()

    try:
        response = requests.post(
            DEEPGRAM_API_URL,
            headers=headers,
            params=params,
            data=audio_bytes,
            timeout=300,
        )
    except requests.exceptions.RequestException as e:
        raise MeetingDiarizationError(f"Deepgram transcription request failed: {e}") from e

    if response.status_code != 200:
        raise MeetingDiarizationError(
            f"Deepgram transcription returned HTTP {response.status_code}: {response.text[:500]}"
        )

    try:
        data = response.json()
        return data["results"]["channels"][0]["alternatives"][0]
    except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError) as e:
        raise MeetingDiarizationError(
            f"Deepgram transcription response did not have the expected shape: {e!r}"
        ) from e


def transcribe_deepgram_segments(audio_path, speaker, language, gap_threshold=0.8):
    """Transcribe a single channel with Deepgram into utterance segments.

    Deepgram returns word level timing; we group consecutive words into
    utterance segments whenever the gap between words exceeds `gap_threshold`
    seconds. No diarisation is requested: each channel is already a single speaker.
    """
    logging.info(f"[DEEPGRAM] Transcribing {speaker} channel (segments)")
    alt = _deepgram_alternative(audio_path)
    words = alt.get("words", [])

    if not words:
        transcript = alt.get("transcript", "").strip()
        if not transcript:
            # This side said nothing in this stretch of audio.
            return []
        raise MeetingDiarizationError(
            f"Deepgram returned text for the {speaker} side without word timings, "
            "so it cannot be placed in order"
        )

    segments = []
    current = None
    for w in words:
        word_text = w.get("punctuated_word") or w.get("word", "")
        start = float(w.get("start", 0.0))
        end = float(w.get("end", 0.0))

        if current is None:
            current = {"speaker": speaker, "text": word_text,
                       "start": start, "end": end, "language": language}
        elif start - current["end"] > gap_threshold:
            segments.append(current)
            current = {"speaker": speaker, "text": word_text,
                       "start": start, "end": end, "language": language}
        else:
            current["text"] += " " + word_text
            current["end"] = end

    if current:
        segments.append(current)

    return segments


def transcribe_channel_chunked(audio_path, speaker, language):
    """
    Transcribe a channel, chunking if necessary.
    Returns list of segments with speaker, text, start, end, language.
    """
    duration = get_audio_duration(audio_path)
    logging.info(f"[CHUNK] Channel duration: {duration:.1f}s")

    if duration <= MAX_DIRECT_DURATION:
        logging.info(f"[CHUNK] Duration under {MAX_DIRECT_DURATION}s, using direct transcription")
        return transcribe_channel_direct(audio_path, speaker, language)

    # Need to chunk
    logging.info(f"[CHUNK] Duration {duration:.1f}s exceeds limit, chunking into {CHUNK_DURATION}s segments")

    chunks = split_audio_into_chunks(audio_path, CHUNK_DURATION, CHUNK_OVERLAP)
    all_segments = []

    try:
        for chunk_path, chunk_start_time in chunks:
            # Transcribe chunk. A failed chunk stops the run rather than leaving a gap.
            chunk_segments = transcribe_channel_direct(chunk_path, speaker, language)

            if chunk_segments:
                # Adjust timestamps
                for seg in chunk_segments:
                    seg['start'] += chunk_start_time
                    seg['end'] += chunk_start_time

                all_segments.extend(chunk_segments)
                logging.info(f"[CHUNK] Transcribed chunk at {chunk_start_time:.1f}s: {len(chunk_segments)} segments")
    finally:
        # Clean up chunk files
        for chunk_path, _ in chunks:
            if chunk_path != audio_path and os.path.exists(chunk_path):
                try:
                    os.remove(chunk_path)
                except:
                    pass

    # Deduplicate overlapping segments
    deduplicated = deduplicate_segments(all_segments, CHUNK_OVERLAP)
    logging.info(f"[CHUNK] Total segments: {len(all_segments)}, after dedup: {len(deduplicated)}")

    return deduplicated


def transcribe_channel_direct(audio_path, speaker, language):
    """Transcribe a single channel directly (no chunking)."""
    logging.info(f"[STEREO] Transcribing {speaker} channel, lang={language}")
    return transcribe_deepgram_segments(audio_path, speaker, language)


def consolidate_segments(segments):
    """
    Sort by midpoint, then merge consecutive same speaker segments.
    """
    if not segments:
        return []

    # Calculate midpoint for each segment
    for seg in segments:
        seg["mid"] = (seg["start"] + seg["end"]) / 2

    # Sort by midpoint
    segments.sort(key=lambda x: x["mid"])

    # Consolidate consecutive same speaker
    consolidated = []
    current = None

    for seg in segments:
        if current is None:
            current = seg.copy()
        elif seg["speaker"] == current["speaker"]:
            # Same speaker: merge
            current["text"] += " " + seg["text"]
            current["end"] = max(current["end"], seg["end"])
        else:
            # Different speaker: save current, start new
            del current["mid"]
            consolidated.append(current)
            current = seg.copy()

    if current:
        if "mid" in current:
            del current["mid"]
        consolidated.append(current)

    return consolidated


def transcribe_stereo(input_path):
    """
    Transcribe stereo recording with speaker separation.
    Left channel = Agent, Right channel = Customer
    Automatically chunks long audio.
    Returns a dict with the ordered conversation.
    """
    logging.info(f"[STEREO] Received: {os.path.basename(input_path)}")

    left_path = input_path + ".left.wav"
    right_path = input_path + ".right.wav"

    try:
        # Extract left channel (agent)
        result = subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-af", "pan=mono|c0=c0",
            "-ar", "16000", "-c:a", "pcm_s16le",
            left_path
        ], capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise MeetingDiarizationError(f"Left channel extraction failed: {result.stderr[-500:]}")

        # Extract right channel (customer)
        result = subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-af", "pan=mono|c0=c1",
            "-ar", "16000", "-c:a", "pcm_s16le",
            right_path
        ], capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise MeetingDiarizationError(f"Right channel extraction failed: {result.stderr[-500:]}")

        # Get total duration
        total_duration = get_audio_duration(input_path)

        # No language is sent to Deepgram, so both sides are transcribed with
        # Deepgram's default language. The label records that.
        left_lang = "en"
        right_lang = "en"

        left_segments = transcribe_channel_chunked(left_path, "agent", left_lang)
        right_segments = transcribe_channel_chunked(right_path, "customer", right_lang)

        # Merge and sort by midpoint
        all_segments = left_segments + right_segments

        # Consolidate using midpoint sorting
        conversation = consolidate_segments(all_segments)

        logging.info(f"[STEREO] Returned {len(conversation)} turns")

        return {
            "conversation": conversation,
            "total_turns": len(conversation),
            "agent_language": left_lang,
            "customer_language": right_lang,
            "model": DEEPGRAM_MODEL,
            "audio_duration_seconds": total_duration,
            "chunking_used": total_duration > MAX_DIRECT_DURATION,
        }

    finally:
        for path in [left_path, right_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
