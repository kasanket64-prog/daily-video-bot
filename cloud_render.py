"""GitHub renderer: short-lived workload identity, no account tokens."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
from bot import http

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
    with urllib.request.build_opener(StockRedirect()).open(url, timeout=90) as response:
        data = response.read(60_000_001)
    if len(data) > 60_000_000:
        raise RuntimeError("Stock clip exceeds the free render size limit")
    path.write_bytes(data)


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
    if not isinstance(materials, list) or not 1 <= len(materials) <= 3:
        raise RuntimeError("Invalid render materials")
    local = []
    for index, material in enumerate(materials):
        destination = out / f"clip-{index}.mp4"
        download_stock(material["url"], destination)
        local.append(str(destination.resolve()))
    meta["local_materials"] = local
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (ROOT / "mpt/config.toml").write_text('[app]\nsubtitle_provider="edge"\nupload_post_enabled=false\nupload_post_auto_upload=false\n', encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "render_cloud.py")], cwd=ROOT / "mpt", check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3300)
    video = (out / "video.mp4").read_bytes()
    if not 0 < len(video) <= 19_000_000:
        raise RuntimeError("Preview must be below 19 MB")
    http("POST", worker + "/render/preview/" + urllib.parse.quote(job["id"], safe=""),
         headers={"Authorization": "Bearer " + identity(worker), "Content-Type": "video/mp4"}, data=video, timeout=300)
    print("Preview delivered. No account credentials were used by this renderer.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Render stopped: {type(error).__name__}. Check Worker configuration, free quotas, and Actions setup.")
        raise SystemExit(1)
