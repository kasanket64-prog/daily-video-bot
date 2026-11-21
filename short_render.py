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


def _scan_gameplay(source, ffmpeg, motion_dir=None):
    command = [
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file",
        "-format_whitelist", "mov,matroska,webm", "-i", str(source), "-map", "0:a:0",
        "-t", "7200", "-af", "aresample=8000,asetnsamples=n=8000:p=0,"
        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-",
    ]
    if motion_dir is not None:
        command.extend(["-map", "0:v:0", "-an", "-t", "7200", "-vf",
                        "fps=1,scale=96:54,signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=motion.txt",
                        "-f", "null", "-"])
    result = subprocess.run(command, cwd=motion_dir, capture_output=True, text=True,
                            check=True, timeout=1080 if motion_dir is not None else 480)
    return [max(-80., float(line.split("=")[1])) for line in result.stdout.splitlines()
            if line.startswith("lavfi.astats.Overall.RMS_level=")]


def gta_levels(source, *, ffmpeg="ffmpeg"):
    return _scan_gameplay(source, ffmpeg)


def gta_signals(source, *, ffmpeg="ffmpeg"):
    """Read the source once and keep motion metadata separate from audio metadata."""
    with TemporaryDirectory() as folder:
        levels = _scan_gameplay(Path(source).resolve(), ffmpeg, folder)
        movement = (Path(folder) / "motion.txt").read_text(encoding="utf-8")
    return levels, [float(line.split("=")[1]) for line in movement.splitlines()
                    if line.startswith("lavfi.signalstats.YDIF=")]


def gta_peaks(levels, movement):
    scored = []
    for i in range(1, len(levels)-1):
        prior = levels[max(0, i-60):i]
        energy = (levels[i] + levels[i+1]) / 2
        jump = energy - max(-50, sum(prior)/len(prior))
        motion = movement[i] if i < len(movement) else 0
        if (energy < -46 or jump < 3) and motion < 12:
            continue
        scored.append((jump + .35 * energy + min(35, motion)*.65, i))
    return scored


def gameplay_moments(levels, movement, used=(), limit=40):
    """Group nearby reactions until activity subsides, then include setup and payoff."""
    end = len(levels) - 1
    events = []
    for score, second in gta_peaks(levels, movement):
        if events and second <= events[-1][1] + 5:
            first, _, best_score, peak = events[-1]
            events[-1] = (first, second, max(score, best_score), second if score > best_score else peak)
        else:
            events.append((second, second, score, second))
    selected = []
    for first, last, score, peak in sorted(events, key=lambda e: -e[2]):
        start, stop = max(0, first-4), min(end, last+3)
        if stop-start > 180:
            start = min(max(start, peak-90), stop-180)
            stop = start+180
        if stop-start < 3 or any(start < b and a < stop for a,b in (*used, *selected)):
            continue
        selected.append((start, stop))
        if len(selected) >= limit:
            break
    return selected


def gta_windows(levels, duration, used=(), limit=40, movement=()):
    last = len(levels) - 1 - math.ceil(duration)
    scored = [(score, min(last, max(0, i-5))) for score, i in gta_peaks(levels, movement)]
    starts = []
    for score, start in sorted(scored, reverse=True):
        if start >= 0 and all(abs(start-other) >= duration for other in (*used, *starts)):
            starts.append(start)
            if len(starts) == limit:
                break
    return starts


def gta_start(source, duration, *, ffmpeg="ffmpeg"):
    starts = gta_windows(gta_levels(source, ffmpeg=ffmpeg), duration, limit=1)
    if not starts:
        raise ValueError("No distinct gameplay highlight")
    return starts[0]


def suggest_start(source, duration, *, ffmpeg="ffmpeg"):
    """Place the strongest sustained audio moment after a short setup."""
    if not 15 <= duration <= 32:
        raise ValueError("Choose a duration of 15â€“32 seconds")
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
        raise ValueError("Choose a nonnegative start and a duration of 15â€“32 seconds")
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
