#!/usr/bin/env python3
"""
One recording of a meeting in, agent and customer turns out.

  1. Downmix the recording and find who speaks when (prepare_meeting.py).
  2. Build the two sided file: first speaker on the left, everyone else on the right.
  3. Transcribe each side (transcribe_sides.py).
  4. Return the turns in order: left is the agent, right is the customer.

Usage:
  python diarize_meeting.py RECORDING [--out turns.json]

Mistral is the default for both speech steps and Deepgram the backup. Needs
MISTRAL_API_KEY, DEEPGRAM_API_KEY or both in the environment, and ffmpeg and
ffprobe on the PATH. When a backup takes over, the result says so and a warning
goes to stderr. Exits with status 1 and a message on stderr if any step fails.
"""
import argparse
import json
import logging
import os
import shutil
import sys
import tempfile

import prepare_meeting
import transcribe_sides
from errors import MeetingDiarizationError


def check_requirements():
    """Stop before any work if something the method needs is missing."""
    if not prepare_meeting.MISTRAL_API_KEY and not prepare_meeting.DEEPGRAM_API_KEY:
        raise MeetingDiarizationError(
            "Neither MISTRAL_API_KEY nor DEEPGRAM_API_KEY is set. "
            "Put your own key for at least one of them in the environment."
        )
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MeetingDiarizationError(f"{tool} was not found on the PATH")


def diarize_meeting(recording_file):
    """Run the whole method on one recording and return the result dict."""
    if not os.path.isfile(recording_file):
        raise MeetingDiarizationError(f"Recording not found: {recording_file}")

    work_dir = tempfile.mkdtemp(prefix="meeting_diarization_")
    try:
        stereo_path, speaker_pass = prepare_meeting.prepare_meeting_recording(recording_file, work_dir)
        result = transcribe_sides.transcribe_stereo(stereo_path)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not result["conversation"]:
        raise MeetingDiarizationError("Transcription returned no turns")

    return {
        "turns": result["conversation"],
        "total_turns": result["total_turns"],
        "speaker_pass": {
            "backend": speaker_pass["backend"],
            "model": speaker_pass["model"],
            "fell_back": bool(speaker_pass["failures"]),
            "failures": speaker_pass["failures"],
        },
        "transcription": {
            "backend": result["backend"],
            "model": result["model"],
            "fell_back": bool(result["failures"]),
            "failures": result["failures"],
        },
        "audio_duration_seconds": result["audio_duration_seconds"],
        "chunking_used": result["chunking_used"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Turn one meeting recording into agent and customer turns."
    )
    parser.add_argument("recording", help="Path to the meeting recording (any format ffmpeg reads)")
    parser.add_argument("--out", help="Write the JSON result to this file instead of stdout")
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        check_requirements()
        output = diarize_meeting(args.recording)
    except MeetingDiarizationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for step, label in (("speaker_pass", "Finding the speakers"), ("transcription", "Transcription")):
        for backend, reason in output[step]["failures"].items():
            print(
                f"warning: {label}: {backend} failed ({reason}); "
                f"used {output[step]['backend']} instead",
                file=sys.stderr,
            )

    text = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
