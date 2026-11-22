"""Render a reviewed highlight from a local media file."""
import argparse
import base64
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


def live_evidence(path, start, duration, *, width, ffmpeg="ffmpeg"):
    def encoded(args):
        data = subprocess.check_output([ffmpeg, "-v", "error", "-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "file", *args],
                                       timeout=30, stderr=subprocess.PIPE)
        return base64.b64encode(data).decode()
    frames = [encoded(["-ss", str(start + duration * t), "-i", str(path), "-frames:v", "1", "-vf",
                       f"scale={width}:-2", "-c:v", "mjpeg", "-q:v", "4", "-threads", "1",
                       "-f", "image2pipe", "-"]) for t in (.04, .18, .35, .52, .72, .92)]
    audio = encoded(["-ss",str(start),"-i", str(path),"-t",str(duration),"-vn", "-ac", "1", "-ar", "16000", "-b:a", "24k", "-f", "mp3", "-"])
    return frames, audio


def render_live(source, moment, folder, policy, plan, *, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    streams = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(source)], timeout=15))["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    w, h = video["width"], video["height"]
    box = plan["facecam"]
    x,y,cw,ch = [int(box[key]*size)//2*2 for key,size in (("x",w),("y",h),("w",w),("h",h))]
    # Keep the source creator in a single panel; crop the gameplay toward the opposite side.
    game_w, game_h = (min(w, int(h * .9) // 2 * 2), h) if w / h > .9 else (w, min(h, int(w / .9) // 2 * 2))
    if w / h > .9:
        game_x = max(0, min(w - game_w, (x + cw if (x + cw / 2) < w / 2 else x - game_w) // 2 * 2))
        game_y = 0
    else:
        game_x = 0
        game_y = max(0, min(h - game_h, (y + ch if (y + ch / 2) < h / 2 else y - game_h) // 2 * 2))
    logo_asset = policy.get("logo_asset")
    no_added_branding = policy.get("no_added_branding") is True
    logo = logo_asset in ("campaign-kreekcraft.webp", "campaign-clipup.webp")
    play_height = 740 if logo_asset == "campaign-kreekcraft.webp" else 730 if logo_asset == "campaign-clipup.webp" else 800
    campaign_text = ("" if no_added_branding else
                     "drawtext=textfile=credit.txt:expansion=none:fontcolor=white:fontsize=26:x=24:y=312,")
    footer_text = ("" if no_added_branding else
                   f",drawtext=textfile=source.txt:expansion=none:fontcolor=white:fontsize={16 if logo else 22}:x=24:y={1040 if logo else 1215}")
    layout = (f"[0:v]split[face][game];[face]crop={cw}:{ch}:{x}:{y},"
              "scale=720:300:force_original_aspect_ratio=increase,crop=720:300,setsar=1[portrait];"
              f"[game]crop={game_w}:{game_h}:{game_x}:{game_y},scale=720:{play_height},setsar=1[play];"
              "color=c=black:s=720x1280:r=30[canvas];[canvas][portrait]overlay=0:0[withface];"
              "[withface][play]overlay=0:350[withplay];"
              + ("[1:v]scale=590:-1[logo];[withplay][logo]overlay=(W-w)/2:1090[branded];[branded]"
                 if logo_asset == "campaign-kreekcraft.webp" else
                 "[1:v]scale=310:-1[logo];[withplay][logo]overlay=(W-w)/2:1080[branded];[branded]"
                 if logo_asset == "campaign-clipup.webp" else "[withplay]")
              + campaign_text
              + "drawtext=textfile=hook.txt:expansion=none:fontcolor=white:fontsize=38:x=(w-text_w)/2:y=370:"
              "box=1:boxcolor=black@0.65:boxborderw=16:enable='lt(t,2)'"
              + footer_text + "[out]")
    (folder / "credit.txt").write_text(policy["credit"], encoding="utf-8")
    (folder / "hook.txt").write_text(plan["hook"], encoding="utf-8")
    (folder / "source.txt").write_text("Source: " + policy.get("source_url", "https://www.twitch.tv/" + policy["user"]), encoding="utf-8")
    output = folder / "reel.mp4"
    duration = moment[1] - moment[0]
    asset = Path(__file__).resolve().parent / "assets" / (logo_asset or "")
    inputs = ["-ss", str(moment[0]), "-i", str(source)]
    if logo:
        if not asset.is_file():
            raise FileNotFoundError("KreekCraft campaign overlay is missing")
        inputs.extend(["-loop", "1", "-i", str(asset)])
    subprocess.run([ffmpeg, "-v", "error", "-y", "-nostdin", "-threads", "2", "-filter_complex_threads", "2",
            *inputs, "-filter_complex", layout,
            "-map", "[out]", "-map", "0:a:0", "-t", str(duration), "-r", "30",
            "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "23",
            "-maxrate", "2200k", "-bufsize", "2200k", "-pix_fmt", "yuv420p",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output)],
            cwd=folder, check=True, timeout=160, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if max(gta_levels(output, ffmpeg=ffmpeg), default=-80) < -50:
        raise ValueError("Silent live export")
    return output
