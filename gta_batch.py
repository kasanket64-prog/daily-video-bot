"""Make up to forty distinct gameplay previews per India-local day."""
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

from cloud_render import http, identity, inspect_and_deliver, worker_url
from gta_live import capture
from short_candidates import choose_candidate
from short_render import gameplay_moments, gta_signals, live_evidence

def ffmpeg(source, args, **kwargs):
    return subprocess.run(["ffmpeg", "-y", "-nostdin", "-v", "error",
        "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm",
        *args[:args.index("INPUT")], "-i", str(source), *args[args.index("INPUT")+1:]],
        check=True, timeout=600, **kwargs)


def transcribe(source, start, duration, folder, model):
    wav = folder / "moment.wav"
    seek = ["-ss", str(start), "INPUT", "-t", str(duration)]
    ffmpeg(source, seek + ["-vn", "-ac", "1", "-ar", "16000", str(wav)])
    segments, info = model.transcribe(str(wav), word_timestamps=True, vad_filter=True)
    segments = list(segments)
    return segments, info.language, " ".join(segment.text.strip() for segment in segments).strip()


def edit(source, start, duration, entry, folder, segments, plan):
    seek = ["-ss", str(start), "INPUT", "-t", str(duration)]
    font = next((path for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                   "C:/Windows/Fonts/arialbd.ttf") if Path(path).is_file()), None)
    if not font:
        raise RuntimeError("No supported caption font found")
    font = font.replace("\\", "/").replace(":", r"\:")
    filters = ["scale=720:960:force_original_aspect_ratio=decrease:force_divisible_by=2",
               "setsar=1", "pad=720:1280:(ow-iw)/2:(oh-ih)/2"]
    words = []
    for segment in segments:
        timed = segment.words or []
        for index in range(0, len(timed), 3):
            phrase = timed[index:index+3]
            text = " ".join(w.word.strip() for w in phrase)
            name = f"caption-{len(words)}.txt"
            (folder / name).write_text(text, encoding="utf-8")
            filters.append(f"drawtext=fontfile='{font}':textfile={name}:expansion=none:fontcolor=white:fontsize=32:"
                f"x=(w-tw)/2:y=1010:box=1:boxcolor=black@0.8:"
                f"enable='between(t,{phrase[0].start:.3f},{phrase[-1].end:.3f})'")
            words.append(text)
    # Keep gameplay and facecam in frame even for wide source recordings.
    (folder / "credit.txt").write_text(entry["credit"][:36], encoding="utf-8")
    filters.append(f"drawtext=fontfile='{font}':textfile=credit.txt:expansion=none:fontcolor=white:fontsize=27:x=(w-tw)/2:y=170")
    (folder / "hook.txt").write_text(plan["hook"], encoding="utf-8")
    (folder / "cta.txt").write_text(plan["cta"], encoding="utf-8")
    filters.append(f"drawtext=fontfile='{font}':textfile=hook.txt:expansion=none:fontcolor=white:fontsize=38:x=(w-tw)/2:y=315:box=1:boxcolor=black@0.75:boxborderw=14:enable='lt(t,2)'")
    filters.append(f"drawtext=fontfile='{font}':textfile=cta.txt:expansion=none:fontcolor=white:fontsize=28:x=(w-tw)/2:y=1150:box=1:boxcolor=black@0.8:boxborderw=12:enable='gte(t\\,{max(0,duration-2.5):.2f})'")
    max_kbps = min(4000, 140000 // duration - 96)
    out = folder / "preview.mp4"
    ffmpeg(source, seek + ["-map", "0:v:0", "-map", "0:a:0", "-vf", ",".join(filters),
        "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-maxrate", f"{max_kbps}k",
        "-bufsize", f"{max_kbps}k", "-af", f"afade=t=in:d=0.03,afade=t=out:st={duration-.03:.2f}:d=0.03", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(out)], cwd=folder)
    return out


def source_windows(entry, folder, used, deadline):
    if entry.get("media_kind") != "live-hls":
        source = folder / "source.mp4"
        subprocess.run(["curl", "--proto", "=https", "--fail", "--silent", "--max-time", "300",
            "--max-filesize", "1000000000", "--output", str(source), "--", entry["media_url"]],
            check=True, timeout=305, stderr=subprocess.DEVNULL)
        for start, stop in gameplay_moments(*gta_signals(source), used):
            yield source, start, start, stop-start
        return

    cache = {}
    previous_end = 0
    while time.monotonic() < deadline:
        try:
            update = capture(entry, folder, previous_end, cache)
        except OSError:
            # A live segment can roll off the playlist during download.
            time.sleep(min(12, max(0, deadline-time.monotonic())))
            continue
        if update:
            source, offset, previous_end, finished = update
            if source is None:
                return
            levels, movement = gta_signals(source)
            prior = [(a-offset, b-offset) for a,b in used]
            for start, stop in gameplay_moments(levels, movement, prior):
                if start == 0 or (not finished and stop >= len(levels)-2):
                    continue  # Wait for a window containing the setup and payoff.
                yield source, start, start+offset, stop-start
            if finished:
                return
        time.sleep(min(12, max(0, deadline-time.monotonic())))


def run(snapshot, catalog, folder):
    from faster_whisper import WhisperModel
    worker = worker_url()

    def post(route, data):
        return http("POST", worker + "/render/" + route,
                    headers={"Authorization": "Bearer " + identity(worker)}, data=data)

    history = post("short-history", {})
    day = snapshot["batchDay"]
    today = [h for h in history if h.get("id", "").startswith(day + "-")]
    occupied = {h.get("slot") or 1 for h in today}
    slots = iter(i for i in range(1, (1 if snapshot["previewOnly"] else 40) + 1) if i not in occupied)
    slot = next(slots, None)
    folder.mkdir(parents=True, exist_ok=True)
    model = None
    delivered = held = 0
    live = os.getenv("GTA_LIVE_RUN") == "true"
    active_ids = {v["source_id"] for v in snapshot["videos"] if v.get("live_started_at")}
    candidates = [e for e in catalog if (e.get("media_kind") == "live-hls") == live
                  and (not live or e["source_id"] in active_ids)]
    deadline = time.monotonic() + 14 * 60
    while slot and candidates:
        entry = choose_candidate(snapshot, candidates, [])
        if not entry:
            break
        sid = entry["source_id"]
        candidates = [e for e in candidates if e["source_id"] != sid]
        prior = [h for h in history if h["source_id"] == sid]
        if any(h.get("start") is None for h in prior):
            continue
        used = [(h["start"], h["start"] + (h.get("duration") or 24)) for h in prior]
        windows = source_windows(entry, folder, used, deadline)
        while slot:
            try:
                source, local_start, start, duration = next(windows)
            except StopIteration:
                break
            except (ValueError, OSError, subprocess.SubprocessError):
                print("Skipping an unreadable gameplay feed or recording", file=sys.stderr)
                break
            if model is None:
                model = WhisperModel("tiny", device="cpu", compute_type="int8")
            clip_duration = min(18, duration)
            try:
                segments, language, transcript = transcribe(source, local_start, clip_duration, folder, model)
            except subprocess.SubprocessError:
                print("Holding a moment that could not be transcribed", file=sys.stderr)
                continue
            try:
                frames, _ = live_evidence(source, local_start, clip_duration, width=360)
            except (ValueError, OSError, subprocess.SubprocessError):
                print("Skipping a clip that could not produce inspection frames", file=sys.stderr)
                continue
            try:
                plan = post("clip-plan", {"frames": frames, "transcript": transcript[:1600],
                    "story": entry["story"][:1000], "source_facts": entry["source_facts"][:2000]})
            except Exception:
                print("AI could not prepare a grounded hook and ending question", file=sys.stderr)
                raise
            if plan.get("usable") is not True:
                held += 1
                continue
            try:
                draft = edit(source, local_start, clip_duration, entry, folder, segments, plan)
            except subprocess.SubprocessError:
                print("Holding a moment that could not be rendered", file=sys.stderr)
                continue
            metadata = {k: entry[k] for k in ("source_id", "credit", "category", "source_facts")}
            metadata.update(slot=slot, start=start, duration=clip_duration, batchDay=day, sources=entry["fact_sources"],
                title=plan["title"], hook=plan["hook"],
                script=transcript[:1600] or "Gameplay audio without dialogue.", clipLanguage=language,
                analysis=dict(angle=entry["story"][:240], audience="GTA VI viewers",
                    story_arc=plan["payoff"], emotion="Reaction",
                    sound_plan="Original cleared stream audio", cta=plan["cta"]))
            job = post("short", metadata)
            used.append((start, start+clip_duration))
            if not job.get("skip"):
                try:
                    with redirect_stdout(sys.stderr):
                        inspect_and_deliver(worker, job["id"], draft, gameplay_duration=clip_duration)
                    delivered += 1
                except RuntimeError as error:
                    if "inspection held this draft" not in str(error):
                        raise
                    held += 1
            slot = next(slots, None)
    return {"delivered": delivered, "held": held, "previously_reserved_today": len(occupied)}


if __name__ == "__main__":
    snapshot_file, catalog_file, output = map(Path, sys.argv[1:])
    print(json.dumps(run(json.loads(snapshot_file.read_text()), json.loads(catalog_file.read_text()),
                         output.resolve())))
