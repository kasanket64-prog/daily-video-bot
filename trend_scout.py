"""Collect YouTube trend candidates without downloading their media."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def rank_videos(items, *, observed_at):
    """Keep YouTube chart order; do not derive custom metrics from API data."""
    videos = []
    for position, item in enumerate(items, 1):
        video_id = item.get("id", "")
        snippet = item["snippet"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue
        source_id = f"youtube:{video_id}"
        videos.append({
            "source_id": source_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet["title"],
            "channel": snippet["channelTitle"],
            "category_id": snippet["categoryId"],
            "published_at": snippet["publishedAt"],
            "chart_position": position,
        })
    return {"observed_at": observed_at.isoformat(), "videos": videos}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="IN")
    parser.add_argument("--cloud-catalog", type=Path, help="Use the Worker and save its catalog privately")
    args = parser.parse_args()
    region = args.region.upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        parser.error("Region must be a two-letter country code")
    if args.cloud_catalog:
        if region != "IN":
            parser.error("The cloud scout uses the India chart")
        from cloud_render import http, identity, worker_url

        worker = worker_url()
        inputs = http("POST", worker + "/render/short-inputs",
                      headers={"Authorization": "Bearer " + identity(worker)}, data={})
        args.cloud_catalog.write_text(json.dumps(inputs["catalog"]), encoding="utf-8")
        snapshot = rank_videos(inputs["items"], observed_at=datetime.now(timezone.utc))
        print(json.dumps({"region": region, **snapshot}, ensure_ascii=True, indent=2))
        return
    key = os.environ.get("YOUTUBE_DATA_API_KEY")
    if not key:
        parser.error("Set YOUTUBE_DATA_API_KEY in the environment")
    query = urlencode({
        "part": "snippet", "chart": "mostPopular", "regionCode": region,
        "maxResults": 50,
    })
    request = Request(f"https://www.googleapis.com/youtube/v3/videos?{query}",
                      headers={"X-Goog-Api-Key": key})
    try:
        with urlopen(request, timeout=30) as response:
            items = json.load(response)["items"]
    except HTTPError as error:
        parser.exit(1, f"YouTube Data API returned HTTP {error.code}\n")
    except (URLError, TimeoutError):
        parser.exit(1, "Could not reach the YouTube Data API\n")
    snapshot = rank_videos(items, observed_at=datetime.now(timezone.utc))
    print(json.dumps({"region": region, **snapshot}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
