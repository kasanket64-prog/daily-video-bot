"""Select a trending Short with a reviewed source file and reuse record."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
import wave

from short_render import render_short, suggest_start
from short_selection import select_short

EDITORIAL_WEIGHTS = {
    "hook": 0.25, "payoff": 0.25, "audience_fit": 0.20,
    "freshness": 0.15, "visual_quality": 0.15,
}


def editorial_score(entry):
    review = entry.get("editorial")
    if not isinstance(review, dict) or any(
        type(review.get(field)) is not int or not 1 <= review[field] <= 5
        for field in EDITORIAL_WEIGHTS
    ):
        raise ValueError("Each source needs owner-reviewed 1–5 editorial ratings")
    score = round(sum(review[field] * weight for field, weight in EDITORIAL_WEIGHTS.items()) * 20)
    if score < 60:
        return None
    return score


def learning_adjustments(history):
    outcomes = {}
    for item in history:
        if not isinstance(item, dict):
            continue
        if item.get("outcome") not in ("approved", "published", "rejected"):
            continue
        if not isinstance(item.get("category"), str):
            continue
        values = outcomes.setdefault(item["category"], [0, 0])
        values[0] += item["outcome"] in ("approved", "published")
        values[1] += 1
    return {
        category: round((2 * approved / total - 1) * 10)
        for category, (approved, total) in outcomes.items() if total >= 3
    }


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
    adjustments = learning_adjustments(history)
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
        if not isinstance(entry.get("source_facts"), str) or not 30 <= len(entry["source_facts"].strip()) <= 4000:
            raise ValueError("Each source needs owner-reviewed factual context")
        if not isinstance(entry.get("fact_sources"), list) or not 1 <= len(entry["fact_sources"]) <= 4:
            raise ValueError("Each source needs 1–4 factual citation URLs")
        for source_url in entry["fact_sources"]:
            if not isinstance(source_url, str):
                raise ValueError("Factual citation URLs must be HTTPS strings")
            url = urlsplit(source_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Factual citation URLs must use HTTPS")
        if any(not isinstance(entry.get(field), str) or not entry[field].strip()
               for field in ("category", "story", "hook")):
            raise ValueError("Each candidate needs a category, story angle and hook")
        if not isinstance(entry["credit"], str) or not entry["credit"].strip():
            raise ValueError("Each reviewed source needs a credit")
        platforms = entry["platforms"]
        if not isinstance(platforms, list) or any(
            platform not in ("youtube", "instagram") for platform in platforms
        ):
            raise ValueError("Platforms must list youtube, instagram, or both")
        base_score = editorial_score(entry)
        entry["learning_adjustment"] = adjustments.get(entry["category"], 0)
        entry["editorial_score"] = (
            None if base_score is None else max(0, min(100, base_score + entry["learning_adjustment"]))
        )
        reviewed[source_id] = entry

    candidates = []
    for video in snapshot["videos"]:
        channel = video.get("channel", "").casefold()
        source_id = video.get("source_id", "").casefold()
        if any(name in channel or name in source_id for name in blocked):
            continue
        entry = reviewed.get(video["source_id"])
        if entry and entry["editorial_score"] is not None and entry["editorial_score"] >= 60 and {"youtube", "instagram"} <= set(entry["platforms"]):
            candidates.append({**entry, "trend": video})
    candidates.sort(key=lambda item: (-item["editorial_score"], item["trend"]["chart_position"]))
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
        auth = {"Authorization": "Bearer " + identity(worker)}
        history += http("POST", worker + "/render/short-history", headers=auth, data={})
    candidate = choose_candidate(snapshot, catalog, history)
    if candidate is not None and args.render_dir:
        from cloud_render import http, identity, worker_url

        worker = worker_url()
        auth = {"Authorization": "Bearer " + identity(worker)}
        plan = http("POST", worker + "/render/short-script", headers=auth, data={
            "source_facts": candidate["source_facts"],
            "sources": candidate["fact_sources"],
            "category": candidate["category"],
        }, timeout=240)
        folder = args.render_dir
        folder.mkdir(parents=True, exist_ok=True)
        narration = folder / "narration.wav"
        pcm = base64.b64decode(plan["audio_pcm"], validate=True)
        if len(pcm) < 24000 or len(pcm) > 4_000_000 or len(pcm) % 2:
            raise RuntimeError("Generated narration audio failed size/format checks")
        with wave.open(str(narration), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(24000)
            audio_file.writeframes(pcm)
        speech_details = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(narration)
        ], timeout=20))
        speech_duration = float(speech_details["format"]["duration"])
        if speech_duration > 31:
            raise RuntimeError("Generated narration is too long for a Short")
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
        duration = max(15, speech_duration + 0.25)
        start = candidate.get("start")
        if start is None:
            start = suggest_start(source, duration)
        render_short(source, draft, start, duration, plan["hook"], narration=narration,
                     script=plan["script"])
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
            metadata = {key: candidate[key] for key in ("source_id", "credit", "category", "source_facts")}
            metadata.update({key: plan[key] for key in ("title", "hook", "script", "analysis")})
            metadata["sources"] = candidate["fact_sources"]
            job = http("POST", worker + "/render/short",
                       headers=auth, data=metadata)
            if not job.get("skip"):
                inspect_and_deliver(worker, job["id"], draft)
    if args.summary and candidate is not None:
        candidate = {
            "selected": {key: candidate[key] for key in ("source_id", "trend")},
            "decision": "selected",
            "editorial_score": candidate["editorial_score"],
            "learning_adjustment": candidate["learning_adjustment"],
            "reason": "Rights and both-platform checks passed; the owner-reviewed concept met the editorial threshold and was fresh against recent history. Category feedback is applied only after three owner decisions.",
        }
        if args.render_dir:
            candidate["rendered"] = True
    elif args.summary:
        candidate = {
            "selected": None,
            "decision": "hold",
            "reason": "No fresh trend candidate passed the rights, platform, blocked-creator and editorial-quality gates.",
        }
    print(json.dumps(candidate, ensure_ascii=True, indent=2))
