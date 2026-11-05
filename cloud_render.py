"""GitHub renderer: short-lived workload identity, no account tokens."""
import json
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
from bot import APIError, http
from creative import background_card

ROOT = Path(__file__).resolve().parent


def worker_url():
    value = os.environ.get("CLOUDFLARE_WORKER_URL", "").rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.username or parsed.fragment:
        raise RuntimeError("Set CLOUDFLARE_WORKER_URL to the Worker HTTPS origin")
    return value


def identity(audience):
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(audience, safe="")
    return http("GET", url, headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})["value"]


def validate_stock_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".pixabay.com") or parsed.username:
        raise RuntimeError("Unexpected stock footage server")


class StockRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        validate_stock_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download_stock(url, path):
    validate_stock_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "daily-video-bot/1.0"})
    with urllib.request.build_opener(StockRedirect()).open(request, timeout=90) as response:
        data = response.read(60_000_001)
    if len(data) > 60_000_000:
        raise RuntimeError("Stock clip exceeds the free render size limit")
    path.write_bytes(data)


def download_materials(materials, out):
    local = []
    for index, material in enumerate(materials):
        destination = out / f"clip-{index}.mp4"
        try:
            download_stock(material["url"], destination)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            print('Stock clip unavailable; continuing with available clips or an original background.')
            continue
        local.append(str(destination.resolve()))
    return local


def main():
    worker = worker_url()
    job = http("POST", worker + "/render/job", headers={"Authorization": "Bearer " + identity(worker)}, data={})
    if job.get("skip"):
        print("Today's render already exists; skipping.")
        return
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    meta = job["metadata"]
    materials = meta.get("materials")
    if not isinstance(materials, list) or not 0 <= len(materials) <= 3:
        raise RuntimeError("Invalid render materials")
    materials_dir = ROOT / 'mpt/storage/local_videos'
    materials_dir.mkdir(parents=True, exist_ok=True)
    local = download_materials(materials, materials_dir)
    if not local:
        destination = materials_dir / 'original-background.mp4'
        card = out / 'fitzee-card.png'
        background_card(meta, card)
        subprocess.run(['ffmpeg', '-y', '-loop', '1', '-i', str(card), '-t', '15', '-r', '15',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(destination)],
            check=True, stdout=subprocess.DEVNULL)
        local.append(str(destination.resolve()))
    meta["local_materials"] = local
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (ROOT / "mpt/config.toml").write_text('[app]\nsubtitle_provider="edge"\nupload_post_enabled=false\nupload_post_auto_upload=false\n', encoding="utf-8")
    print("Starting credential-free video renderer.", flush=True)
    subprocess.run([sys.executable, str(ROOT / "render_cloud.py")], cwd=ROOT / "mpt", check=True,
                   timeout=3300)
    inspect_and_deliver(worker, job['id'], out / 'video.mp4')


def inspect_and_deliver(worker, job_id, path):
    video = path.read_bytes()
    if not 0 < len(video) <= 19_000_000:
        raise RuntimeError("Preview must be below 19 MB")
    details = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', str(path)]))
    duration = float(details['format']['duration'])
    streams = details['streams']
    visual = next(stream for stream in streams if stream['codec_type'] == 'video')
    if not 15 <= duration <= 32 or visual['width'] != 720 or visual['height'] != 1280 or not any(stream['codec_type'] == 'audio' for stream in streams):
        raise RuntimeError('Draft failed duration, portrait format, or audio inspection')
    frames = []
    for fraction in (0.04, 0.18, 0.35, 0.52, 0.72, 0.92):
        frame = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(duration * fraction), '-i', str(path),
            '-frames:v', '1', '-vf', 'scale=360:640', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '4', '-threads', '1', '-'])
        frames.append(base64.b64encode(frame).decode('ascii'))
    audio = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ac', '1',
        '-ar', '16000', '-b:a', '48k', '-f', 'mp3', '-'])
    inspection = http('POST', worker + '/render/inspect/' + job_id,
        headers={'Authorization': 'Bearer ' + identity(worker)}, data={
            'sha256': hashlib.sha256(video).hexdigest(), 'duration': duration, 'frames': frames,
            'audio': base64.b64encode(audio).decode('ascii')}, timeout=240)
    if inspection.get('passed') is not True:
        raise RuntimeError('Automatic inspection held this draft; no approval request or upload was sent')
    print('Automatic inspection passed for this exact video.', flush=True)
    http("POST", worker + "/render/preview/" + urllib.parse.quote(job_id, safe=""),
         headers={"Authorization": "Bearer " + identity(worker), "Content-Type": "video/mp4"}, data=video, timeout=300)
    print("Preview delivered. No account credentials were used by this renderer.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if isinstance(error, APIError):
            print(str(error))  # The HTTP helper exposes only status codes, never provider bodies or URLs.
        print(f"Render stopped: {type(error).__name__}. Check Worker configuration, free quotas, and Actions setup.")
        raise SystemExit(1)
