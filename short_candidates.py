"""Select a trending Short with a reviewed source file and reuse record."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from short_render import render_short, suggest_start
from short_selection import select_short


def choose_candidate(snapshot, catalog, history):
    """Require reviewed reuse evidence before treating a discovered video as footage."""
    reviewed = {}
    required_rights = (
        "rights_owner_verified", "editing_allowed", "commercial_use_allowed",
        "audio_cleared", "people_cleared",
    )
    blocked = {name.strip().casefold() for name in os.getenv(
        "SHORT_BLOCKED_CREATORS", "Nikhil Kamath"
    ).split(",") if name.strip()}
    for entry in catalog:
        source_id = entry["source_id"]
        if source_id in reviewed:
            raise ValueError(f"Duplicate source in reviewed catalog: {source_id}")
        for field in ("media_url", "rights_url"):
            url = urlsplit(entry[field])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError(f"{field} must be an HTTPS URL without credentials")
        if entry.get("rights_type") not in (
            "cc0", "cc-by-4.0", "written-permission", "public-domain"
        ):
            raise ValueError("Each source needs a supported, reviewed rights_type")
        if not all(entry.get(field) is True for field in required_rights):
            raise ValueError("Each source needs verified rights, edit, commercial, audio and people clearances")
        if entry["rights_type"] == "cc-by-4.0" and not entry.get("license_url", "").startswith(
            "https://creativecommons.org/licenses/by/4.0/"
        ):
            raise ValueError("CC BY sources need the official CC BY 4.0 license URL")
        if entry["rights_type"] == "written-permission" and not entry.get("permission_evidence_url"):
            raise ValueError("Written permission needs a reviewable evidence URL")
        if entry["rights_type"] == "public-domain" and not entry.get("public_domain_evidence_url"):
            raise ValueError("Public-domain claims need a reviewable evidence URL")
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
        channel = video.get("channel", "").casefold()
        source_id = video.get("source_id", "").casefold()
        if any(name in channel or name in source_id for name in blocked):
            continue
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
        duration = candidate.get("duration", 15)
        start = candidate.get("start")
        if start is None:
            start = suggest_start(source, duration)
        render_short(source, draft, start, duration, candidate["hook"])
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json",
            str(draft),
        ], timeout=30))
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        if (
            (video["width"], video["height"]) != (720, 1280)
            or not any(stream["codec_type"] == "audio" for stream in probe["streams"])
            or abs(float(probe["format"]["duration"]) - duration) > 0.25
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
