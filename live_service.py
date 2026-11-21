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
from urllib.error import HTTPError

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from yt_dlp import YoutubeDL
from short_render import live_evidence, render_live, replay_start

ROOT = Path(__file__).resolve().parent
ORIGIN = "https://daily-video-approvals.kasanket64.workers.dev"
CHANNEL = "UCeoZXkaJDtdTHafgoZeDcAA"
lock = threading.Lock()
last_result = None
spec = importlib.util.spec_from_file_location("neon_highlights", ROOT / "third-party/neonclipping/highlights.py")
neon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(neon)
neon.cv2.setNumThreads(1)
public_key = load_pem_public_key((ROOT / "live-public.pem").read_bytes())


def verified(body, signature, now=None):
    public_key.verify(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)), body)
    job = json.loads(body)
    now = time.time() if now is None else now
    if (job.get("callback") != ORIGIN or job.get("channel") != CHANNEL
            or job.get("source_id") not in ("twitch:lacy", "twitch:reviewed")
            or not isinstance(job.get("token"), str) or not 30 < len(job["token"]) < 2000
            or type(job.get("exp")) not in (int, float)
            or not now < job["exp"] <= now + 300):
        raise ValueError("Invalid work request")
    return job


def post(job, route, data, content_type="application/json"):
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    request = Request(ORIGIN + "/live/" + route, data=body, method="POST",
                      headers={"Authorization": "Bearer " + job["token"], "Content-Type": content_type,
                               "User-Agent": "daily-video-bot/1.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        error.gateway = "provider"
        if "application/json" in error.headers.get("Content-Type", ""):
            try:
                label = json.loads(error.read(1000)).get("error")
                if label in ("Denied", "Live monitoring disabled"):
                    error.gateway = label
            except (ValueError, UnicodeDecodeError):
                pass
        raise


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


def inspection(path, duration):
    details = probe(path)
    visual = next(s for s in details["streams"] if s["codec_type"] == "video")
    if (visual["width"], visual["height"]) != (720, 1280) or abs(float(details["format"]["duration"]) - duration) > .15:
        raise ValueError("Invalid export")
    raw = path.read_bytes()
    if not 0 < len(raw) < 19_000_000:
        raise ValueError("Invalid export size")
    frames,audio=live_evidence(path,0,duration,width=360)
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
        creators = job.get("creators", [])
        if not creators:
            raise ValueError("Missing reviewed creators")
        for policy in creators:
            user = policy.get("user")
            if user not in ("clix", "kreekcraft", "lacy"):
                continue
            result["stage"] = "lookup"
            try:
                with YoutubeDL({"quiet": True, "logger": Quiet(), "socket_timeout": 10,
                                "retries": 0, "extractor_retries": 0}) as client:
                    stream = client.extract_info("https://www.twitch.tv/" + user, download=False)
            except Exception:
                continue
            if (not stream.get("is_live") or stream.get("uploader_id", "").casefold() != user
                    or not re.search(r"GTA\s*(6|VI)\b", stream.get("description", "") + stream.get("title", ""), re.I)):
                continue
            if not re.fullmatch(r"[0-9]{9,20}", str(stream.get("id", ""))):
                continue
            job["source_id"] = "twitch:" + str(stream["id"])
            used = [(x["start"], x["start"] + x.get("duration", 24)) for x in history
                    if x.get("source_id") == job["source_id"] and x.get("start") is not None]
            for mode in (("live","replay1","replay2") if user=="kreekcraft" else ("live",)):
                capture,seek,absolute=stream,[],math.floor(time.time())-30
                if mode!="live":
                    result["stage"]="lookup"
                    try:
                        with YoutubeDL({"quiet":True,"logger":Quiet(),"socket_timeout":10,
                                        "retries":0,"extractor_retries":0,"live_from_start":True}) as client:
                            capture=client.extract_info("https://www.twitch.tv/"+user,download=False)
                        offset=replay_start(stream,capture,job["token"]+mode)
                        seek=["-ss",str(offset)]
                        absolute=int(capture["timestamp"])+offset
                    except Exception:
                        continue
                formats = [f for f in capture["formats"] if 360 <= (f.get("height") or 0) <= 720]
                if not formats:
                    continue
                selected = min(formats, key=lambda f: abs(f["height"] - 480))
                with TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    source = folder / "live.mkv"
                    result["stage"] = "capture"
                    try:
                        ffmpeg(["-rw_timeout", "15000000", "-protocol_whitelist", "https,tls,tcp,crypto",
                                *seek, "-i", selected["url"], "-t", "90", "-fs", "64000000", "-map", "0:v:0",
                                "-map", "0:a:0", "-c", "copy", str(source)], folder)
                    except subprocess.SubprocessError:
                        continue
                    duration = float(probe(source)["format"]["duration"])
                    if duration < 24:
                        continue
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
                        result["stage"] = "plan_frames"
                        frames,_ = live_evidence(source,start,24,width=640)
                        result["stage"] = "plan"
                        plan = post(job,"plan",{"creator":user,"frames":frames})
                        if plan.get("usable") is not True:
                            result["screened"] = result.get("screened",0) + 1
                            continue
                        slot = slots.pop(0)
                        metadata = dict(source_id=job["source_id"], creator=user, slot=slot, start=absolute+start,
                            capture_mode="live" if mode=="live" else "replay",
                            duration=24, batchDay=job["batchDay"], category="GTA 6 gameplay",
                            credit=policy["credit"], source_facts=policy["facts"],
                            sources=[policy["campaign"], "https://www.twitch.tv/" + user] +
                                (["https://www.twitch.tv/videos/"+capture["id"][1:]] if mode!="live" else []),
                            title=plan["title"], hook=plan["hook"],
                            script="Editorial summary of the source highlight. " + plan["payoff"], clipLanguage="en",
                            analysis=dict(angle=plan["payoff"][:240], audience="GTA VI viewers",
                            story_arc=plan["payoff"][:240], emotion="Surprise",
                            sound_plan="Original synchronized stream commentary and gameplay audio", cta="Watch the outcome"))
                        result["stage"] = "reservation"
                        reservation = post(job,"short",metadata)
                        if reservation.get("skip"):
                            continue
                        result["stage"] = "render"
                        output = render_live(source,(start,stop),folder,policy,plan)
                        raw,review = inspection(output,24)
                        result["stage"] = "inspection"
                        approved = post(job,"inspect/"+reservation["id"],review)
                        used.append((absolute+start,absolute+stop))
                        if approved.get("passed") is True:
                            result["stage"] = "delivery"
                            post(job,"preview/"+reservation["id"],raw,"video/mp4")
                            result["delivered"] += 1
                        else:
                            result["held"] += 1
                    if result["delivered"] or not slots:
                        break
            if result["delivered"] or not slots:
                break
    except Exception as error:
        result["state"] = "failed"
        result["error_type"] = type(error).__name__
        if hasattr(error, "code"):
            result["http_status"] = error.code
            result["gateway"] = getattr(error, "gateway", "upstream")
        if isinstance(error, subprocess.CalledProcessError):
            result["returncode"] = error.returncode
            if error.stderr and not any("https://" in str(arg) for arg in error.cmd):
                result["media_error"] = error.stderr.decode(errors="replace")[-400:]
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
