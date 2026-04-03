#!/usr/bin/env python3
"""Speaker-diarized transcription: PyAnnote diarization + mlx_whisper, run in parallel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path

# --- Constants ---

WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"
PYANNOTE_MODEL = "pyannote/speaker-diarization-community-1"

ADJECTIVES = [
    "Skittish", "Contemplative", "Effervescent", "Wistful", "Rambunctious",
    "Pensive", "Jubilant", "Laconic", "Spirited", "Mellow",
    "Intrepid", "Whimsical", "Steadfast", "Luminous", "Candid",
    "Dapper", "Serene", "Vivacious", "Plucky", "Cryptic",
    "Breezy", "Earnest", "Zesty", "Coy", "Gallant",
    "Nimble", "Quaint", "Buoyant", "Wry", "Tenacious",
    "Gentle", "Fierce", "Dreamy", "Brisk", "Sly",
    "Jolly", "Demure", "Radiant", "Spry", "Balmy",
]

NOUNS = [
    "Banana", "Owl", "Teapot", "Cactus", "Narwhal",
    "Zeppelin", "Porcupine", "Umbrella", "Flamingo", "Cobalt",
    "Biscuit", "Pangolin", "Gondola", "Walrus", "Origami",
    "Tangerine", "Capybara", "Quasar", "Hedgehog", "Pretzel",
    "Anchovy", "Platypus", "Sextant", "Kumquat", "Toucan",
    "Piccolo", "Armadillo", "Gazelle", "Lantern", "Mongoose",
    "Crouton", "Ibex", "Macaroon", "Starling", "Turnip",
    "Okapi", "Waffle", "Chameleon", "Thimble", "Yak",
]


# --- HuggingFace Token ---

def get_hf_token() -> str:
    token = os.environ.get("HF_TOKEN")
    if token:
        return token

    try:
        from huggingface_hub import HfFolder
        token = HfFolder.get_token()
        if token:
            return token
    except ImportError:
        pass

    # Try reading cached token directly
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.exists():
        token = token_path.read_text().strip()
        if token:
            return token

    print("Error: HuggingFace token required for PyAnnote speaker diarization.", file=sys.stderr)
    print("", file=sys.stderr)
    print("  export HF_TOKEN=$(passveil show huggingface.co/doma@doma.dev/Big_Token_Doma)", file=sys.stderr)
    print("", file=sys.stderr)
    print("Or: huggingface-cli login", file=sys.stderr)
    print("", file=sys.stderr)
    print("You must also accept model terms at:", file=sys.stderr)
    print("  https://huggingface.co/pyannote/speaker-diarization-community-1", file=sys.stderr)
    print("  https://huggingface.co/pyannote/segmentation-3.0", file=sys.stderr)
    sys.exit(1)


# --- Speaker Name Generation ---

def generate_speaker_name(speaker_id: str, seed: str) -> str:
    h = hashlib.sha256(f"{seed}:{speaker_id}".encode()).digest()
    adj_idx = int.from_bytes(h[0:4], "big") % len(ADJECTIVES)
    noun_idx = int.from_bytes(h[4:8], "big") % len(NOUNS)
    return f"{ADJECTIVES[adj_idx]} {NOUNS[noun_idx]}"


def build_speaker_map(speaker_ids: list[str], audio_path: str) -> dict[str, str]:
    seed = str(Path(audio_path).resolve())
    name_map: dict[str, str] = {}
    used_names: set[str] = set()
    for sid in sorted(speaker_ids):
        name = generate_speaker_name(sid, seed)
        # Handle unlikely collision by appending a suffix
        attempt = 0
        base_name = name
        while name in used_names:
            attempt += 1
            name = f"{base_name} {attempt}"
        used_names.add(name)
        name_map[sid] = name
    return name_map


# --- Audio Loading (ffmpeg, bypasses broken torchcodec) ---

def load_audio_as_waveform(audio_path: str, sample_rate: int = 16000) -> dict:
    """Load audio via ffmpeg and return as pyannote-compatible waveform dict."""
    import numpy as np
    import torch

    cmd = [
        "ffmpeg", "-i", audio_path,
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ar", str(sample_rate), "-ac", "1",
        "-loglevel", "error",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")

    audio = np.frombuffer(result.stdout, dtype=np.float32)
    waveform = torch.from_numpy(audio).unsqueeze(0)  # (1, samples)
    return {"waveform": waveform, "sample_rate": sample_rate}


# --- Diarization (PyAnnote, CPU) ---

def run_diarization(
    audio_path: str, hf_token: str, num_speakers: int | None = None,
) -> list[tuple[float, float, str]]:
    import torch
    from pyannote.audio import Pipeline

    print("  [diarize] Loading audio via ffmpeg...", file=sys.stderr)
    audio_data = load_audio_as_waveform(audio_path)

    print("  [diarize] Loading PyAnnote pipeline...", file=sys.stderr)
    pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=hf_token)
    device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
    pipeline.to(device)
    print(f"  [diarize] Using device: {device}", file=sys.stderr)

    print("  [diarize] Running speaker diarization...", file=sys.stderr)
    output = pipeline(audio_data, num_speakers=num_speakers)
    # PyAnnote 4.x returns DiarizeOutput; extract the Annotation
    diarization = getattr(output, "speaker_diarization", output)

    turns: list[tuple[float, float, str]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append((turn.start, turn.end, speaker))

    print(f"  [diarize] Found {len(set(t[2] for t in turns))} speakers, {len(turns)} turns", file=sys.stderr)
    return turns


# --- Transcription (mlx_whisper, MLX/GPU) ---

def run_transcription(audio_path: str, word_level: bool = False) -> list[dict]:
    import mlx_whisper

    print("  [whisper] Transcribing with Whisper large-v3...", file=sys.stderr)
    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=WHISPER_MODEL,
        condition_on_previous_text=False,
        hallucination_silence_threshold=1.0,
        word_timestamps=word_level,
        verbose=False,
    )

    segments = result["segments"]
    print(f"  [whisper] Transcribed {len(segments)} segments", file=sys.stderr)
    return segments


# --- Alignment ---

def align_segments(
    whisper_segments: list[dict],
    speaker_turns: list[tuple[float, float, str]],
    word_level: bool = False,
) -> list[dict]:
    """Assign a speaker to each whisper segment (or word) by majority temporal overlap."""

    def find_speaker(start: float, end: float) -> str:
        overlap_by_speaker: dict[str, float] = {}
        for turn_start, turn_end, speaker in speaker_turns:
            overlap_start = max(start, turn_start)
            overlap_end = min(end, turn_end)
            if overlap_end > overlap_start:
                overlap_by_speaker[speaker] = (
                    overlap_by_speaker.get(speaker, 0.0) + (overlap_end - overlap_start)
                )
        if not overlap_by_speaker:
            return "Unknown"
        return max(overlap_by_speaker, key=overlap_by_speaker.get)  # type: ignore[arg-type]

    if not word_level:
        for seg in whisper_segments:
            seg["speaker"] = find_speaker(seg["start"], seg["end"])
        return whisper_segments

    # Word-level: assign each word individually, then merge consecutive same-speaker spans
    merged: list[dict] = []
    for seg in whisper_segments:
        words = seg.get("words", [])
        if not words:
            seg["speaker"] = find_speaker(seg["start"], seg["end"])
            merged.append(seg)
            continue
        for word_info in words:
            speaker = find_speaker(word_info["start"], word_info["end"])
            if merged and merged[-1]["speaker"] == speaker:
                merged[-1]["text"] += word_info["word"]
                merged[-1]["end"] = word_info["end"]
            else:
                merged.append({
                    "start": word_info["start"],
                    "end": word_info["end"],
                    "text": word_info["word"],
                    "speaker": speaker,
                })
    return merged


# --- Output ---

def format_time(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:06.3f}"
    return f"{int(m):02d}:{s:06.3f}"


def write_output(
    segments: list[dict],
    speaker_map: dict[str, str],
    output_path: str,
    fmt: str,
) -> None:
    def speaker_name(seg: dict) -> str:
        return speaker_map.get(seg.get("speaker", ""), seg.get("speaker", "Unknown"))

    if fmt == "json":
        data = {
            "speakers": speaker_map,
            "segments": [
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "speaker": speaker_name(seg),
                    "speaker_id": seg.get("speaker", "Unknown"),
                    "text": seg["text"].strip(),
                }
                for seg in segments
            ],
        }
        path = f"{output_path}.json"
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote {path}", file=sys.stderr)
        return

    lines: list[str] = []
    prev_speaker = None

    for seg in segments:
        name = speaker_name(seg)
        text = seg["text"].strip()
        if not text:
            continue

        if fmt == "timestamped":
            ts = f"[{format_time(seg['start'])} --> {format_time(seg['end'])}]"
            if prev_speaker is not None and name != prev_speaker:
                lines.append("")
            lines.append(f"{ts} {name}: {text}")
        else:  # text
            if prev_speaker is not None and name != prev_speaker:
                lines.append("")
            lines.append(f"{name}: {text}")

        prev_speaker = name

    path = f"{output_path}.txt"
    Path(path).write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}", file=sys.stderr)


# --- CLI ---

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe audio with speaker diarization (PyAnnote + mlx_whisper).",
    )
    parser.add_argument("audio", help="Path to audio file (any format ffmpeg supports)")
    parser.add_argument("output", help="Output file name (without extension)")
    parser.add_argument(
        "--format", choices=["text", "timestamped", "json"], default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--num-speakers", type=int, default=None,
        help="Exact number of speakers (auto-detected if omitted)",
    )
    parser.add_argument(
        "--word-level", action="store_true",
        help="Use word-level timestamps for finer speaker alignment (slower)",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"Error: Audio file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    hf_token = get_hf_token()
    audio_str = str(audio_path)

    # Run diarization and transcription in parallel
    # PyAnnote uses CPU (torch), mlx_whisper uses GPU (MLX) -- no contention
    print(f"Processing: {audio_path.name}", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=2) as pool:
        diarize_future: Future = pool.submit(
            run_diarization, audio_str, hf_token, args.num_speakers,
        )
        transcribe_future: Future = pool.submit(
            run_transcription, audio_str, args.word_level,
        )

        # Collect results (re-raises exceptions from threads)
        try:
            speaker_turns = diarize_future.result()
        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "403" in error_msg:
                print("Error: HuggingFace token rejected. Accept model terms at:", file=sys.stderr)
                print(f"  https://huggingface.co/{PYANNOTE_MODEL}", file=sys.stderr)
                print("  https://huggingface.co/pyannote/segmentation-3.0", file=sys.stderr)
                sys.exit(1)
            raise

        whisper_segments = transcribe_future.result()

    if not speaker_turns:
        print("Warning: No speakers detected. Outputting plain transcription.", file=sys.stderr)
        for seg in whisper_segments:
            seg["speaker"] = "Unknown"
        speaker_map: dict[str, str] = {}
    else:
        # Align and name
        whisper_segments = align_segments(whisper_segments, speaker_turns, args.word_level)
        speaker_ids = sorted(set(seg.get("speaker", "Unknown") for seg in whisper_segments) - {"Unknown"})
        speaker_map = build_speaker_map(speaker_ids, audio_str)

    write_output(whisper_segments, speaker_map, args.output, args.format)

    # Print speaker legend
    if speaker_map:
        print("\nSpeakers:", file=sys.stderr)
        for sid, name in speaker_map.items():
            print(f"  {sid} -> {name}", file=sys.stderr)


if __name__ == "__main__":
    main()
