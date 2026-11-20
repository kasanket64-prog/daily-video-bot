"""Make up to forty distinct gameplay previews per India-local day."""
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from cloud_render import http, identity, inspect_and_deliver, worker_url
from short_candidates import choose_candidate
from short_render import gameplay_moments, gta_levels

def ffmpeg(source, args, **kwargs):
    return subprocess.run(["ffmpeg", "-y", "-nostdin", "-v", "error",
        "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm",
        *args[:args.index("INPUT")], "-i", str(source), *args[args.index("INPUT")+1:]],
        check=True, timeout=600, **kwargs)


def motion(source):
    result = ffmpeg(source, ["INPUT", "-map", "0:v:0", "-an", "-t", "7200",
        "-vf", "fps=1,scale=96:54,signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=-",
        "-f", "null", "-"], capture_output=True, text=True)
    return [float(line.split("=")[1]) for line in result.stdout.splitlines()
            if line.startswith("lavfi.signalstats.YDIF=")]


def edit(source, start, duration, entry, folder, model):
    wav = folder / "moment.wav"
    seek = ["-ss", str(start), "INPUT", "-t", str(duration)]
    ffmpeg(source, seek + ["-vn", "-ac", "1", "-ar", "16000", str(wav)])
    segments, info = model.transcribe(str(wav), word_timestamps=True, vad_filter=True)
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
            filters.append(f"drawtext=textfile={name}:expansion=none:fontcolor=white:fontsize=32:"
                f"x=(w-tw)/2:y=1010:box=1:boxcolor=black@0.8:"
                f"enable='between(t,{phrase[0].start:.3f},{phrase[-1].end:.3f})'")
            words.append(text)
    # Keep gameplay and facecam in frame even for wide source recordings.
    (folder / "credit.txt").write_text(entry["credit"][:36], encoding="utf-8")
    filters.append("drawtext=textfile=credit.txt:expansion=none:fontcolor=white:fontsize=27:x=(w-tw)/2:y=170")
    max_kbps = min(4000, 140000 // duration - 96)
    out = folder / "preview.mp4"
    ffmpeg(source, seek + ["-map", "0:v:0", "-map", "0:a:0", "-vf", ",".join(filters),
        "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-maxrate", f"{max_kbps}k",
        "-bufsize", f"{max_kbps}k", "-af", f"afade=t=in:d=0.03,afade=t=out:st={duration-.03:.2f}:d=0.03", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(out)], cwd=folder)
    return out, " ".join(words), info.language


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
    source = folder / "source.mp4"
    model = None
    delivered = held = 0
    candidates = list(catalog)
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
        try:
            subprocess.run(["curl", "--proto", "=https", "--fail", "--silent", "--max-time", "300",
                "--max-filesize", "1000000000", "--output", str(source), "--", entry["media_url"]],
                check=True, timeout=305, stderr=subprocess.DEVNULL)
            moments = gameplay_moments(gta_levels(source), motion(source), used)
        except (ValueError, subprocess.SubprocessError):
            print("Skipping an unreadable gameplay recording", file=sys.stderr)
            continue
        for start, stop in moments:
            duration = stop - start
            if not slot:
                break
            if model is None:
                model = WhisperModel("tiny", device="cpu", compute_type="int8")
            try:
                draft, transcript, language = edit(source, start, duration, entry, folder, model)
            except subprocess.SubprocessError:
                print("Holding a moment that could not be rendered", file=sys.stderr)
                continue
            hook = (transcript[:64].rsplit(" ", 1)[0] or transcript[:64]) if transcript else entry["hook"][:64]
            metadata = {k: entry[k] for k in ("source_id", "credit", "category", "source_facts")}
            metadata.update(slot=slot, start=start, duration=duration, batchDay=day, sources=entry["fact_sources"],
                title=f"GTA VI | {hook} ({start//60}:{start%60:02d})", hook=hook,
                script=transcript[:1600] or "Gameplay audio without dialogue.", clipLanguage=language,
                analysis=dict(angle=entry["story"][:240], audience="GTA VI viewers",
                    story_arc=f"Gameplay highlight at {start} seconds", emotion="Reaction",
                    sound_plan="Original cleared stream audio", cta="Watch the outcome"))
            job = post("short", metadata)
            if not job.get("skip"):
                try:
                    with redirect_stdout(sys.stderr):
                        inspect_and_deliver(worker, job["id"], draft, gameplay_duration=duration)
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
