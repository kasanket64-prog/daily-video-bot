"""Run NeonClipping on signed, time-limited requests from the approval Worker."""
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from itertools import islice
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
from short_render import live_evidence, render_live

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
                details = json.loads(error.read(1000))
                label = details.get("error")
                if label in ("Denied", "Live monitoring disabled"):
                    error.gateway = label
                if details.get("provider") == "Gemini" and type(details.get("provider_status")) is int and 400 <= details["provider_status"] <= 599:
                    error.gateway = "Gemini"
                    error.provider_status = details["provider_status"]
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


def process_media(job, policy, history, source, folder, absolute, source_url, slots, result, deadline):
    duration = float(probe(source)["format"]["duration"])
    if duration < 12:
        return False
    length = min(24, int(duration))
    used = [(x["start"], x["start"] + x.get("duration", 24)) for x in history
            if x.get("source_id") == job["source_id"] and x.get("start") is not None]
    result["stage"] = "selection"
    for candidate in neon.rank(source, duration, count=2, length=length):
        if time.monotonic() >= deadline or not slots:
            return False
        start = int(candidate["start"])
        stop = start + length
        if (stop > duration or (candidate.get("features", {}).get("motion") or 0) < .015
                or any(absolute + start < b and a < absolute + stop for a, b in used)):
            continue
        result["stage"] = "plan_frames"
        try:
            frames, _ = live_evidence(source, start, length, width=640)
        except subprocess.CalledProcessError:
            result["damaged_windows"] = result.get("damaged_windows", 0) + 1
            continue
        result["stage"] = "plan"
        recent = [str(x.get("payoff") or x.get("title") or x.get("hook"))[:240]
                  for x in history[-20:] if x.get("payoff") or x.get("title") or x.get("hook")]
        plan = post(job, "plan", {"creator": policy["user"], "frames": frames, "recent_events": recent})
        if plan.get("usable") is not True:
            result["screened"] = result.get("screened", 0) + 1
            continue
        slot = slots.pop(0)
        metadata = dict(source_id=job["source_id"], creator=policy["user"], slot=slot, start=absolute+start,
            duration=length, batchDay=job["batchDay"], category="GTA 6 gameplay",
            credit=policy["credit"], source_facts=policy["facts"], sources=[policy["campaign"], source_url],
            title=plan["title"], hook=plan["hook"],
            script="Editorial summary of the source highlight. " + plan["payoff"], clipLanguage="en",
            analysis=dict(angle=plan["payoff"][:240], audience="GTA VI viewers", story_arc=plan["payoff"][:240],
                emotion="Surprise", sound_plan="Original synchronized stream commentary and gameplay audio", cta="Watch the outcome"))
        result["stage"] = "reservation"
        reservation = post(job, "short", metadata)
        if reservation.get("skip"):
            continue
        result["stage"] = "render"
        output = render_live(source, (start, stop), folder, policy, plan)
        raw, review = inspection(output, length)
        result["stage"] = "inspection"
        approved = post(job, "inspect/" + reservation["id"], review)
        used.append((absolute+start, absolute+stop))
        history.append({**metadata, "id": reservation["id"]})
        if approved.get("passed") is True:
            result["stage"] = "delivery"
            post(job, "preview/" + reservation["id"], raw, "video/mp4")
            result["delivered"] += 1
            return True
        result["held"] += 1
    return True


def capture_media(job, policy, history, media, source_url, slots, result, deadline, *, live):
    formats = [f for f in media.get("formats", []) if 360 <= (f.get("height") or 0) <= 720]
    if not formats:
        return False
    selected = min(formats, key=lambda f: abs(f["height"] - 480))
    job["source_id"] = "twitch:" + str(media["id"])
    with TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "live.mkv"
        absolute = math.floor(time.time()) - 30 if live else 0
        result["stage"] = "capture"
        try:
            ffmpeg(["-rw_timeout", "15000000", "-protocol_whitelist", "https,tls,tcp,crypto",
                    "-i", selected["url"], "-t", str(90 if live else min(media["duration"], 90)),
                    "-fs", "64000000", "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", str(source)], folder)
        except subprocess.SubprocessError:
            return False
        return process_media(job, policy, history, source, folder, absolute, source_url, slots, result, deadline)


def recent_clips(client, job, policy, history, seen, result, deadline):
    result["stage"] = "clip_lookup"
    try:
        listing = client.extract_info("https://www.twitch.tv/" + policy["user"] + "/clips?filter=clips&range=24hr", download=False, process=False)
    except Exception:
        result["lookup_failures"] = result.get("lookup_failures", 0) + 1
        return
    used = {x.get("source_id") for x in history} | seen
    cutoff = max(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp(), time.time()-86400)
    checked = 0
    for entry in islice(listing.get("entries", []), 20):
        if time.monotonic() >= deadline or checked >= 2:
            break
        clip_id = str(entry.get("id", ""))
        url = entry.get("url", "")
        source_id = "twitch:" + clip_id
        if (not re.fullmatch(r"[0-9]{9,20}", clip_id) or source_id in used
                or not re.fullmatch(r"https://www\.twitch\.tv/" + policy["user"] + r"/clip/[A-Za-z0-9_-]+", url)):
            continue
        checked += 1
        try:
            clip = client.extract_info(url, download=False)
        except Exception:
            continue
        eligible = (str(clip.get("id")) == clip_id and str(clip.get("channel_id")) == policy["clips_channel_id"]
            and isinstance(clip.get("timestamp"), (int, float)) and cutoff <= clip["timestamp"] <= time.time()+300
            and any(str(c).casefold() in ("grand theft auto vi", "grand theft auto 6", "gta vi", "gta 6") for c in clip.get("categories", []))
            and isinstance(clip.get("duration"), (int, float)) and 12 <= clip["duration"] <= 90)
        if eligible:
            yield clip, url
        else:
            post(job, "clip-history", {"creator": policy["user"], "source_id": source_id})
            seen.add(source_id)


def run(job):
    global last_result
    result = {"delivered": 0, "held": 0, "state": "complete", "stage": "lookup"}
    try:
        history = post(job, "short-history", {})
        slots = [n for n in range(1, 41) if not any(x["id"] == job["batchDay"] + f"-g{n:02d}-short" for x in history)]
        if not slots:
            return
        creators = job.get("creators", [])
        if not creators:
            raise ValueError("Missing reviewed creators")
        creator_order = [policy.get("user") for policy in creators]
        last_creator = next((item.get("creator") for item in reversed(history)
                             if item.get("id", "").startswith(job["batchDay"] + "-g")
                             and item.get("creator") in creator_order), None)
        if last_creator:
            index = creator_order.index(last_creator) + 1
            creators = creators[index:] + creators[:index]
        seen = set(post(job, "clip-history", {})) if any(p.get("clips_channel_id") for p in creators) else set()
        # Finish before the signed callback expires, including bounded AI retries.
        deadline = time.monotonic() + 600
        for policy in creators:
            user = policy.get("user")
            if user not in ("clix", "kreekcraft", "lacy") or time.monotonic() >= deadline:
                continue
            result["stage"] = "lookup"
            with YoutubeDL({"quiet": True, "logger": Quiet(), "socket_timeout": 10,
                            "retries": 0, "extractor_retries": 0}) as client:
                try:
                    stream = client.extract_info("https://www.twitch.tv/" + user, download=False)
                except Exception:
                    stream = None
                if (stream and stream.get("is_live") and stream.get("uploader_id", "").casefold() == user
                        and re.search(r"GTA\s*(6|VI)\b", stream.get("description", "") + stream.get("title", ""), re.I)
                        and re.fullmatch(r"[0-9]{9,20}", str(stream.get("id", "")))):
                    capture_media(job, policy, history, stream, "https://www.twitch.tv/" + user, slots, result, deadline, live=True)
                if result["delivered"] or not slots:
                    break
                if policy.get("clips_channel_id"):
                    for clip, url in recent_clips(client, job, policy, history, seen, result, deadline):
                        complete = capture_media(job, policy, history, clip, url, slots, result, deadline, live=False)
                        if complete:
                            post(job, "clip-history", {"creator": user, "source_id": "twitch:" + str(clip["id"])})
                            seen.add("twitch:" + str(clip["id"]))
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
            if hasattr(error, "provider_status"):
                result["provider_status"] = error.provider_status
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
                   {"engine": "NeonClipping", "revision": os.environ.get("RENDER_GIT_COMMIT", "unknown")[:12], "busy": lock.locked(),
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
