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


def rank_videos(items, previous=None, *, observed_at):
    old = {video["source_id"]: video["views"] for video in previous["videos"]} if previous else {}
    elapsed = (
        (observed_at - datetime.fromisoformat(previous["observed_at"])).total_seconds() / 3600
        if previous else 0
    )
    videos = []
    for position, item in enumerate(items, 1):
        video_id = item.get("id", "")
        snippet = item["snippet"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or "viewCount" not in item.get("statistics", {}):
            continue
        source_id = f"youtube:{video_id}"
        views = int(item["statistics"]["viewCount"])
        growth = (
            round((views - old[source_id]) / elapsed, 2)
            if elapsed > 0 and source_id in old and views >= old[source_id] else None
        )
        videos.append({
            "source_id": source_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet["title"],
            "channel": snippet["channelTitle"],
            "category_id": snippet["categoryId"],
            "published_at": snippet["publishedAt"],
            "chart_position": position,
            "views": views,
            "new_views_per_hour": growth,
        })
    videos.sort(key=lambda video: (
        -(video["new_views_per_hour"] or 0), video["chart_position"]
    ))
    return {"observed_at": observed_at.isoformat(), "videos": videos}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="IN")
    parser.add_argument("--previous", type=Path, help="Previous scout JSON from the same region")
    args = parser.parse_args()
    region = args.region.upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        parser.error("Region must be a two-letter country code")
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    if previous and previous.get("region") != region:
        parser.error("The previous snapshot must use the same region")
    key = os.environ.get("YOUTUBE_DATA_API_KEY")
    if not key:
        parser.error("Set YOUTUBE_DATA_API_KEY in the environment")
    query = urlencode({
        "part": "snippet,statistics", "chart": "mostPopular", "regionCode": region,
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
    snapshot = rank_videos(items, previous, observed_at=datetime.now(timezone.utc))
    print(json.dumps({"region": region, **snapshot}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
