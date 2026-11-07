"""Render a reviewed highlight from a local media file."""
import argparse
from array import array
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory


def suggest_start(source, duration, *, ffmpeg="ffmpeg"):
    """Place the strongest sustained audio moment after a short setup."""
    if not 15 <= duration <= 32:
        raise ValueError("Choose a duration of 15–32 seconds")
    rate = 8000
    raw = subprocess.check_output([
        ffmpeg, "-nostdin", "-loglevel", "error", "-protocol_whitelist", "file",
        "-format_whitelist", "mov,matroska,webm", "-i", str(source),
        "-map", "0:a:0", "-t", "180", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-",
    ], timeout=60)
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < duration * rate:
        raise ValueError("Source is shorter than the requested Short")
    # shortcut: crowd and speech energy are only a proxy for the payoff; inspect the draft before delivery.
    scores = [
        sum(sample * sample for sample in samples[index:index + rate])
        for index in range(0, len(samples) - rate + 1, rate)
    ]
    peak = max(range(len(scores) - 1), key=lambda index: scores[index] + scores[index + 1])
    if scores[peak] + scores[peak + 1] < 2 * rate * 150**2:
        raise ValueError("Audio has no clear highlight cue")
    return min(max(0, peak - 5), len(samples) / rate - duration)


def render_short(source, destination, start, duration, hook, *, narration, script, ffmpeg="ffmpeg"):
    if not math.isfinite(start) or start < 0 or not 15 <= duration <= 32:
        raise ValueError("Choose a nonnegative start and a duration of 15–32 seconds")
    if not hook.strip() or len(hook.splitlines()) > 2 or any(
        len(line) > 32 for line in hook.splitlines()
    ):
        raise ValueError("Use a hook of one or two lines, up to 32 characters per line")
    if not script.strip() or len(script.split()) > 60:
        raise ValueError("Use a short original narration script")

    source = Path(source).resolve(strict=True)
    narration = Path(narration).resolve(strict=True)
    destination = Path(destination).resolve()
    if source == destination or destination.suffix.lower() != ".mp4":
        raise ValueError("Choose a separate MP4 destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as folder:
        folder = Path(folder)
        (folder / "hook.txt").write_text(hook, encoding="utf-8")
        speech = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(narration)
        ], timeout=20))
        speech_duration = min(float(speech["format"]["duration"]), duration)
        chunks = []
        current = ""
        for word in re.findall(r"\S+", script):
            proposed = f"{current} {word}".strip()
            if current and len(proposed) > 30:
                chunks.append(current)
                current = word
            else:
                current = proposed
        if current:
            chunks.append(current)
        total_words = sum(len(chunk.split()) for chunk in chunks)
        elapsed_words = 0
        caption_filters = []
        # shortcut: caption times are estimated by word count; add forced alignment if review finds persistent drift.
        for index, text in enumerate(chunks):
            caption = folder / f"caption-{index}.txt"
            caption.write_text(text, encoding="utf-8")
            begin = speech_duration * elapsed_words / total_words
            elapsed_words += len(text.split())
            end = speech_duration * elapsed_words / total_words
            caption_filters.append(
                f"drawtext=textfile={caption.name}:expansion=none:fontcolor=white:fontsize=30:"
                f"x=(w-tw)/2:y=1030:box=1:boxcolor=black@0.65:boxborderw=10:"
                f"enable='between(t\\,{begin:.2f}\\,{end:.2f})'"
            )
        draft = folder / "draft.mp4"
        filters = (
            "scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            "setsar=1,pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x10151b,"
            "drawtext=textfile=hook.txt:expansion=none:fontcolor=white:fontsize=36:"
            "x=(w-tw)/2:y=195:line_spacing=10," + ",".join(caption_filters)
        )
        subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm",
            "-ss", str(start), "-i", str(source),
            "-protocol_whitelist", "file", "-format_whitelist", "wav", "-i", str(narration),
            "-t", str(duration),
            "-map", "0:v:0", "-filter_complex",
            "[0:a:0]volume=0.18[bg];[1:a:0]volume=1.0[voice];[bg][voice]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "[a]", "-vf", filters,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", str(draft),
        ], cwd=folder, check=True, timeout=180)
        draft.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, help="Override automatic cut timing")
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--hook", required=True)
    parser.add_argument("--narration", type=Path, required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    start = args.start if args.start is not None else suggest_start(args.source, args.duration, ffmpeg=args.ffmpeg)
    render_short(args.source, args.output, start, args.duration, args.hook,
                 narration=args.narration, script=args.script,
                 ffmpeg=args.ffmpeg)
