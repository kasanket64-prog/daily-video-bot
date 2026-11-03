"""Run inside the pinned MPT checkout using credential-free local materials."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
from creative import caption_font, check_glyphs

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "mpt"))
from app.models.schema import MaterialInfo, VideoParams
from app.services.task import start

meta = json.loads((ROOT / "out/metadata.json").read_text(encoding="utf-8"))
font = caption_font(meta["language"])
check_glyphs(font, meta['script'])
(ROOT / "mpt/resource/fonts" / font.name).write_bytes(font.read_bytes())
params = VideoParams(video_subject=meta["title"], video_script=meta["script"], video_terms=meta["terms"],
    video_source="local", video_materials=[MaterialInfo(provider="local", url=p) for p in meta["local_materials"]],
    video_language=meta["language"], voice_name="hi-IN-SwaraNeural-Female" if meta["language"] == "hi" else "en-IN-NeerjaNeural-Female",
    video_aspect="9:16", video_count=1, n_threads=2, bgm_type="", video_clip_duration=2,
    subtitle_enabled=True, font_name=font.name, font_size=88, stroke_width=5,
    subtitle_position="two_thirds_bottom", subtitle_display_mode="word_by_word",
    subtitle_animation="pop_spring", text_fore_color="#FFE45C", voice_rate=1.06)
result = start(str(uuid.uuid4()), params)
if not result or not result.get("videos"):
    raise RuntimeError("MoneyPrinterTurbo did not produce a video")
subprocess.run(["ffmpeg", "-y", "-i", result["videos"][0], "-vf", "scale=720:1280", "-c:v", "libx264",
    "-preset", "fast", "-b:v", "900k", "-maxrate", "1100k", "-bufsize", "2200k", "-pix_fmt", "yuv420p",
    "-r", "30", "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-movflags", "+faststart",
    str(ROOT / "out/video.mp4")], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
