"""Find candidate Commons videos and preserve their published reuse metadata."""
import argparse
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def reusable_videos(pages):
    candidates = []
    for page in sorted(pages, key=lambda entry: entry.get("index", 0)):
        for info in page.get("imageinfo", [])[:1]:
            metadata = info.get("extmetadata", {})
            license_name = metadata.get("LicenseShortName", {}).get("value")
            credit = metadata.get("Artist", {}).get("value", "")
            credit = unescape(re.sub(r"<[^>]*>", "", credit)).strip()
            media = urlsplit(info.get("url", ""))
            source = urlsplit(info.get("descriptionurl", ""))
            if (
                license_name != "CC0" or not credit
                or metadata.get("Restrictions", {}).get("value", "").strip()
                or info.get("mime") not in ("video/webm", "video/mp4")
                or not 0 < info.get("size", 0) <= 60_000_000
                or (media.scheme, media.netloc) != ("https", "upload.wikimedia.org")
                or (source.scheme, source.netloc) != ("https", "commons.wikimedia.org")
            ):
                continue
            candidates.append({
                "source_id": f"commons:{page['pageid']}",
                "title": page["title"],
                "media_url": media.geturl(),
                "rights_url": source.geturl(),
                "license": license_name,
                "credit": credit,
            })
    return candidates


def search(query_text):
    query = urlencode({
        "action": "query", "format": "json", "formatversion": 2,
        "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"filetype:video {query_text}", "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
        "iiextmetadatafilter": "LicenseShortName|Artist|Restrictions",
    })
    request = Request("https://commons.wikimedia.org/w/api.php?" + query,
                      headers={"User-Agent": "DailyVideoBot/1.0 (footage discovery pilot)"})
    with urlopen(request, timeout=20) as response:
        pages = json.load(response).get("query", {}).get("pages", [])
    return reusable_videos(pages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="Subject to search for on Wikimedia Commons")
    parser.add_argument("--snapshot", type=Path, help="Search for the five highest-ranked trend titles")
    args = parser.parse_args()
    if (args.query is None) == (args.snapshot is None):
        parser.error("Supply one search query or one trend snapshot")
    if args.snapshot:
        videos = json.loads(args.snapshot.read_text(encoding="utf-8"))["videos"]
        # These are discovery leads. A title match does not establish that the file depicts the event.
        result = [
            {"trend_source_id": video["source_id"], "matches": search(video["title"][:150])}
            for video in videos[:5]
        ]
    else:
        result = search(args.query)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
