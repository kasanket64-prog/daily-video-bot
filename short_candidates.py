"""Select a trending Short with a reviewed source file and reuse record."""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from short_render import render_short
from short_selection import select_short


def choose_candidate(snapshot, catalog, history):
    """The catalog is owner-reviewed. YouTube metadata is discovery evidence."""
    reviewed = {}
    for entry in catalog:
        source_id = entry["source_id"]
        if source_id in reviewed:
            raise ValueError(f"Duplicate source in reviewed catalog: {source_id}")
        for field in ("media_url", "rights_url"):
            url = urlsplit(entry[field])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError(f"{field} must be an HTTPS URL without credentials")
        if not isinstance(entry["license"], str) or not entry["license"].strip():
            raise ValueError("Each reviewed source needs a license or permission record")
        if not isinstance(entry["credit"], str) or not entry["credit"].strip():
            raise ValueError("Each reviewed source needs a credit")
        platforms = entry["platforms"]
        if not isinstance(platforms, list) or any(
            platform not in ("youtube", "instagram") for platform in platforms
        ):
            raise ValueError("Platforms must list youtube, instagram, or both")
        reviewed[source_id] = entry

    candidates = []
    for video in snapshot["videos"]:
        entry = reviewed.get(video["source_id"])
        if entry and {"youtube", "instagram"} <= set(entry["platforms"]):
            candidates.append({**entry, "trend": video})
    return select_short(candidates, history)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("catalog", type=Path, help="Owner-reviewed footage catalog")
    parser.add_argument("history", type=Path, help="Draft history, oldest first")
    parser.add_argument("--summary", action="store_true", help="Omit catalog links and permission records")
    parser.add_argument("--render-dir", type=Path, help="Keep the draft and source in a private working directory")
    parser.add_argument("--deliver", action="store_true", help="Submit the draft to the Worker for inspection and approval")
    args = parser.parse_args()
    if args.deliver and not args.render_dir:
        parser.error("--deliver requires --render-dir")
    snapshot, catalog, history = (
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.snapshot, args.catalog, args.history)
    )
    if args.deliver:
        from cloud_render import http, identity, inspect_and_deliver, worker_url

        worker = worker_url()
        history += http("POST", worker + "/render/short-history",
                        headers={"Authorization": "Bearer " + identity(worker)}, data={})
    candidate = choose_candidate(snapshot, catalog, history)
    if candidate is not None and args.render_dir:
        folder = args.render_dir
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "source-media"
        # The reviewed media URL must resolve directly to a file.
        downloaded = subprocess.run([
            "curl", "--proto", "=https", "--fail", "--silent", "--max-time", "90",
            "--max-filesize", "60000000", "--output", str(source), "--",
            candidate["media_url"],
        ], capture_output=True, timeout=95)
        if downloaded.returncode:
            raise RuntimeError("Could not download the reviewed media file")
        draft = folder / "preview.mp4"
        render_short(source, draft, candidate["start"], candidate["duration"], candidate["hook"])
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json",
            str(draft),
        ], timeout=30))
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        if (
            (video["width"], video["height"]) != (720, 1280)
            or not any(stream["codec_type"] == "audio" for stream in probe["streams"])
            or abs(float(probe["format"]["duration"]) - candidate["duration"]) > 0.25
            or draft.stat().st_size > 19_000_000
        ):
            raise RuntimeError("Draft failed format, duration, audio or size checks")
        if args.deliver:
            metadata = {key: candidate[key] for key in ("source_id", "hook", "story", "credit", "category")}
            metadata["title"] = candidate["trend"]["title"]
            job = http("POST", worker + "/render/short",
                       headers={"Authorization": "Bearer " + identity(worker)}, data=metadata)
            if not job.get("skip"):
                inspect_and_deliver(worker, job["id"], draft)
    if args.summary and candidate is not None:
        candidate = {key: candidate[key] for key in ("source_id", "trend")}
        if args.render_dir:
            candidate["rendered"] = True
    print(json.dumps(candidate, ensure_ascii=True, indent=2))
