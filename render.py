"""Run from pinned MoneyPrinterTurbo checkout with its dependencies installed."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "mpt"))
from app.models.schema import VideoParams
from app.services.task import start

meta = json.loads((ROOT / "out/metadata.json").read_text(encoding="utf-8"))
font = Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf")
if not font.is_file():
    font = next(Path("/usr/share/fonts").rglob("NotoSansDevanagari-Regular.ttf"))
destination = ROOT / "mpt/resource/fonts" / font.name
destination.write_bytes(font.read_bytes())
params = VideoParams(video_subject=meta["title"], video_script=meta["script"],
    video_terms=meta["terms"], video_source="pexels", video_language=meta["language"],
    voice_name="hi-IN-SwaraNeural-Female" if meta["language"] == "hi" else "en-IN-NeerjaNeural-Female",
    video_aspect="9:16", video_count=1, n_threads=2, bgm_type="", subtitle_enabled=True,
    font_name=font.name)
result = start(str(uuid.uuid4()), params)
if not result or not result.get("videos"):
    raise RuntimeError("MoneyPrinterTurbo failed to produce a video")
subprocess.run(["ffmpeg", "-y", "-i", result["videos"][0], "-vf", "scale=720:1280",
    "-c:v", "libx264", "-preset", "fast", "-crf", "26", "-pix_fmt", "yuv420p", "-r", "30",
    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
    str(ROOT / "out/video.mp4")], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
