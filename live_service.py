"""Run NeonClipping on signed, time-limited requests from the approval Worker."""
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from yt_dlp import YoutubeDL

ROOT = Path(__file__).resolve().parent
ORIGIN = "https://daily-video-approvals.kasanket64.workers.dev"
CHANNEL = "UCeoZXkaJDtdTHafgoZeDcAA"
lock = threading.Lock()
last_result = None
spec = importlib.util.spec_from_file_location("neon_highlights", ROOT / "third-party/neonclipping/highlights.py")
neon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(neon)
public_key = load_pem_public_key((ROOT / "live-public.pem").read_bytes())


def verified(body, signature, now=None):
    public_key.verify(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)), body)
    job = json.loads(body)
    now = time.time() if now is None else now
    if (job.get("callback") != ORIGIN or job.get("channel") != CHANNEL
            or job.get("source_id") != "twitch:lacy"
            or not isinstance(job.get("token"), str) or not 30 < len(job["token"]) < 2000
            or type(job.get("exp")) not in (int, float)
            or not now < job["exp"] <= now + 300):
        raise ValueError("Invalid work request")
    return job


def post(job, route, data, content_type="application/json"):
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    request = Request(ORIGIN + "/live/" + route, data=body, method="POST",
                      headers={"Authorization": "Bearer " + job["token"], "Content-Type": content_type})
    with urlopen(request, timeout=180) as response:
        return json.load(response)


class Quiet:
    def debug(self, *args):
        pass

    warning = error = debug


def ffmpeg(args, cwd):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-threads", "2",
                    "-filter_complex_threads", "2", *args], cwd=cwd, check=True,
                   timeout=160, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe(path):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format",
                      "-show_streams", "-of", "json", str(path)], timeout=15))


def render(source, moment, folder):
    streams = probe(source)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    w, h = video["width"], video["height"]
    # Lacy's approved layout has the facecam in the upper-left quarter.
    layout = (f"[0:v]split[face][game];[face]crop={w//4*2//2}:{h//4*2//2}:0:0,"
              "scale=720:380,setsar=1,pad=720:1280:0:110:color=0x17131e[top];"
              f"[game]crop={w}:{h-h//4}:0:{h//4},scale=720:410,setsar=1[play];"
              "[top][play]overlay=0:525,drawtext=textfile=credit.txt:expansion=none:"
              "fontcolor=white:fontsize=28:x=34:y=36,"
              "drawtext=textfile=hook.txt:expansion=none:fontcolor=white:fontsize=38:x=34:y=990,"
              "drawtext=textfile=source.txt:expansion=none:fontcolor=white:fontsize=26:x=34:y=1200[out]")
    (folder / "credit.txt").write_text("Ad | #LACY", encoding="utf-8")
    (folder / "hook.txt").write_text("Watch Lacy's next move", encoding="utf-8")
    (folder / "source.txt").write_text("Lacy / twitch.tv/lacy", encoding="utf-8")
    output = folder / "reel.mp4"
    duration = moment[1] - moment[0]
    ffmpeg(["-ss", str(moment[0]), "-i", str(source), "-f", "lavfi", "-i",
            "anullsrc=channel_layout=mono:sample_rate=48000", "-filter_complex", layout,
            "-map", "[out]", "-map", "1:a", "-t", str(duration), "-r", "30",
            "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "23",
            "-maxrate", "2200k", "-bufsize", "2200k", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", str(output)], folder)
    return output


def inspection(path, duration):
    details = probe(path)
    visual = next(s for s in details["streams"] if s["codec_type"] == "video")
    if (visual["width"], visual["height"]) != (720, 1280) or abs(float(details["format"]["duration"]) - duration) > .15:
        raise ValueError("Invalid export")
    raw = path.read_bytes()
    if not 0 < len(raw) < 19_000_000:
        raise ValueError("Invalid export size")
    def encoded(args):
        data = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "2", *args],
                                       timeout=30, stderr=subprocess.DEVNULL)
        return base64.b64encode(data).decode()
    frames = [encoded(["-ss", str(duration * t), "-i", str(path), "-frames:v", "1", "-vf",
                       "scale=360:640", "-c:v", "mjpeg", "-q:v", "4", "-threads", "1",
                       "-f", "image2pipe", "-"]) for t in (.04, .18, .35, .52, .72, .92)]
    audio = encoded(["-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "24k", "-f", "mp3", "-"])
    return raw, {"duration": duration, "sha256": hashlib.sha256(raw).hexdigest(), "frames": frames, "audio": audio}


def run(job):
    global last_result
    result = {"delivered": 0, "held": 0, "state": "complete", "stage": "lookup"}
    try:
        history = post(job, "short-history", {})
        used = []
        slots = [n for n in range(1, 41) if not any(x["id"] == job["batchDay"] + f"-g{n:02d}-short" for x in history)]
        if not slots:
            return
        with YoutubeDL({"quiet": True, "logger": Quiet(), "socket_timeout": 15, "retries": 1}) as client:
            stream = client.extract_info("https://www.twitch.tv/lacy", download=False)
        if not stream.get("is_live") or not re.search(r"GTA\s*(6|VI)\b", stream.get("description", "") + stream.get("title", ""), re.I):
            result["state"] = "offline"
            return
        if stream.get("uploader_id", "").casefold() != "lacy" or not re.fullmatch(r"[0-9]{9,20}", str(stream.get("id", ""))):
            raise ValueError("Wrong live broadcast")
        job["source_id"] = "twitch:" + str(stream["id"])
        used = [(x["start"], x["start"] + x.get("duration", 24)) for x in history
                if x.get("source_id") == job["source_id"] and x.get("start") is not None]
        formats = [f for f in stream["formats"] if 360 <= (f.get("height") or 0) <= 720]
        if not formats:
            raise ValueError("No playable video")
        selected = min(formats, key=lambda f: abs(f["height"] - 480))
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "live.mkv"
            absolute = math.floor(time.time()) - 30
            result["stage"] = "capture"
            ffmpeg(["-rw_timeout", "15000000", "-protocol_whitelist", "https,tls,tcp,crypto",
                    "-i", selected["url"], "-t", "90", "-fs", "64000000", "-map", "0:v:0",
                    "-map", "0:a:0", "-c", "copy", str(source)], folder)
            duration = float(probe(source)["format"]["duration"])
            if duration < 24:
                raise ValueError("Live capture too short")
            result["stage"] = "selection"
            moments = neon.rank(source, duration, count=2, length=24)
            for candidate in moments:
                start = int(candidate["start"])
                stop = start + 24
                if (stop > duration or (candidate.get("features", {}).get("motion") or 0) < .015
                        or any(absolute + start < b and a < absolute + stop for a, b in used)):
                    continue
                if not slots:
                    break
                slot = slots.pop(0)
                metadata = dict(source_id=job["source_id"], slot=slot, start=absolute+start,
                    duration=24, batchDay=job["batchDay"], category="GTA 6 gameplay",
                    credit="Ad | #LACY | twitch.tv/lacy", source_facts=job["source_facts"],
                    sources=["https://reachclipping.com/LACYGTA", "https://www.twitch.tv/lacy"],
                    title="Lacy's next move in GTA VI", hook="Watch Lacy's next move",
                    script="Muted editorial highlight. Follow Lacy's reaction and the visible gameplay.",
                    clipLanguage="en", analysis=dict(angle="Live gameplay and reaction", audience="GTA VI viewers",
                    story_arc="Setup, visible action and reaction", emotion="Surprise",
                    sound_plan="Muted stream audio", cta="Watch the outcome"))
                result["stage"] = "reservation"
                reservation = post(job, "short", metadata)
                if reservation.get("skip"):
                    continue
                result["stage"] = "render"
                output = render(source, (start, stop), folder)
                raw, review = inspection(output, 24)
                result["stage"] = "inspection"
                approved = post(job, "inspect/" + reservation["id"], review)
                used.append((absolute+start, absolute+stop))
                if approved.get("passed") is True:
                    result["stage"] = "delivery"
                    post(job, "preview/" + reservation["id"], raw, "video/mp4")
                    result["delivered"] += 1
                else:
                    result["held"] += 1
    except Exception as error:
        result["state"] = "failed"
        result["error_type"] = type(error).__name__
        if hasattr(error, "code"):
            result["http_status"] = error.code
    finally:
        last_result = result
        try:
            post(job, "report", result)
        except Exception as error:
            result["report_error"] = type(error).__name__
            if hasattr(error, "code"):
                result["report_status"] = error.code
        print(json.dumps(result), flush=True)
        lock.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 404,
                   {"engine": "NeonClipping", "revision": "3a3da401", "busy": lock.locked(),
                    "last_result": last_result} if self.path == "/health" else {})

    def do_POST(self):
        if self.path != "/watch":
            return self.reply(404, {})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 10000:
                raise ValueError("Invalid length")
            job = verified(self.rfile.read(length), self.headers.get("X-Live-Signature", ""))
        except Exception:
            return self.reply(403, {"error": "Denied"})
        if not lock.acquire(blocking=False):
            return self.reply(409, {"busy": True})
        threading.Thread(target=run, args=(job,), daemon=True).start()
        self.reply(202, {"accepted": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "10000"))), Handler).serve_forever()
