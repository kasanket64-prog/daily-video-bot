"""Collect finished windows from a creator's timestamped MPEG-TS HLS media playlist."""
from datetime import datetime
import math
from pathlib import Path
import subprocess
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(url, limit):
    with build_opener(NoRedirect()).open(url, timeout=15) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Feed exceeded download budget")
    return data


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Broadcast clock needs a timezone")
    return stamp.timestamp()


def window(playlist, url):
    """Return the latest continuous media window, dropping gaps and clock jumps."""
    if not playlist.startswith("#EXTM3U") or any(t in playlist for t in
            ("#EXT-X-KEY:", "#EXT-X-MAP:", "#EXT-X-BYTERANGE:", "#EXT-X-STREAM-INF:")):
        raise ValueError("Requires an unencrypted full-segment MPEG-TS media playlist")
    origin = urlsplit(url)
    segments = []
    instant = duration = None
    if origin.scheme != "https" or not origin.hostname or origin.username or origin.password:
        raise ValueError("Requires a creator HTTPS feed")
    for line in map(str.strip, playlist.splitlines()):
        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            clock = timestamp(line.split(":", 1)[1])
            if instant is not None and abs(instant-clock) > 0.25:
                segments.clear()
            instant = clock
        elif line in ("#EXT-X-DISCONTINUITY", "#EXT-X-GAP"):
            segments.clear()
            instant = None
        elif line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",")[0])
            if not math.isfinite(duration) or not 0 < duration <= 30:
                raise ValueError("Invalid segment duration")
        elif line and not line.startswith("#"):
            media = urljoin(url, line)
            target = urlsplit(media)
            if target.scheme != "https" or target.netloc != origin.netloc or target.username or target.password:
                raise ValueError("Segment outside reviewed feed origin")
            if instant is not None and duration is not None:
                segments.append((instant, duration, media))
                instant += duration
            duration = None
    if not segments:
        return []
    end = segments[-1][0] + segments[-1][1]
    return [part for part in segments if end - part[0] <= 120]


def capture(entry, folder, previous_end, cache, *, fetch=download, ffmpeg="ffmpeg"):
    url = entry["media_url"]
    listing = fetch(url, 512_000).decode("utf-8-sig")
    finished = "#EXT-X-ENDLIST" in listing.splitlines()
    parts = window(listing, url)
    if not parts or sum(p[1] for p in parts) < 18:
        return (None, 0, previous_end, True) if finished else None
    end = parts[-1][0] + parts[-1][1]
    if end <= previous_end and not finished:
        return None
    origin = timestamp(entry["trend"]["live_started_at"])
    offset = round(parts[0][0] - origin)
    if offset < 0:
        return None
    # The cache belongs to one feed. Reuse overlapping segments on each poll.
    for key in list(cache):
        if key not in parts:
            del cache[key]
    size = sum(map(len, cache.values()))
    transport = Path(folder) / "live.ts"
    with transport.open("wb") as out:
        for part in parts:
            if part not in cache:
                data = fetch(part[2], min(12_000_000, 64_000_000 - size))
                if not data or data[0] != 0x47:
                    raise ValueError("Invalid MPEG-TS segment")
                cache[part] = data
                size += len(data)
            out.write(cache[part])
    source = Path(folder) / "live.mkv"
    subprocess.run([ffmpeg, "-y", "-nostdin", "-v", "error", "-protocol_whitelist", "file",
                    "-f", "mpegts", "-i", str(transport), "-map", "0:v:0", "-map", "0:a:0",
                    "-c", "copy", str(source)], check=True, timeout=45, stderr=subprocess.DEVNULL)
    return source, offset, end, finished
