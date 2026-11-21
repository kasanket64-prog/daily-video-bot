from collections import Counter
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import gta_batch
from gta_live import capture, window


FEED = "https://creator.example/live/index.m3u8"
CLOCK = "2026-11-21T00:00:00Z"


def playlist(count, ended=False):
    lines = ["#EXTM3U", "#EXT-X-PROGRAM-DATE-TIME:" + CLOCK]
    for i in range(count):
        lines.extend(["#EXTINF:4,", f"{i:02}.ts"])
    return "\n".join(lines + (["#EXT-X-ENDLIST"] if ended else []))


class LiveTests(unittest.TestCase):
    def test_feed_boundaries(self):
        listing = playlist(6)
        for bad in (listing.replace("00.ts", "https://other.example/data"),
                    listing + "\n#EXT-X-KEY:METHOD=AES-128"):
            with self.assertRaises(ValueError):
                window(bad, FEED)
        self.assertEqual(window(listing.replace("#EXTINF:4,\n05.ts", "#EXT-X-GAP\n#EXTINF:4,\n05.ts"), FEED), [])

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires FFmpeg")
    def test_capture_across_segments_waits_for_payoff_and_deduplicates(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=size=96x54:rate=10:duration=36", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=36", "-af", "volume=0.002:enable='not(between(t,17,23))'",
                "-c:v", "mpeg2video", "-g", "10", "-sc_threshold", "1000000000",
                "-c:a", "mp2", "-f", "segment", "-segment_time", "4",
                "-segment_format", "mpegts", str(folder / "%02d.ts")], check=True)
            listings = iter([playlist(5), playlist(8), playlist(9, ended=True)])
            gets = Counter()
            def fetch(url, limit):
                gets[url] += 1
                if url == FEED:
                    return next(listings).encode()
                return (folder / url.rsplit("/", 1)[-1]).read_bytes()
            def poll(entry, folder, end, cache):
                return capture(entry, folder, end, cache, fetch=fetch)
            entry = {"media_kind": "live-hls", "media_url": FEED, "trend": {"live_started_at": CLOCK}}
            used = []
            with patch("gta_batch.capture", side_effect=poll), patch("gta_batch.time.sleep"):
                for _, local_start, start, duration in gta_batch.source_windows(entry, folder, used, time.monotonic()+60):
                    self.assertGreaterEqual(gets[FEED], 2)
                    self.assertEqual(start, local_start)
                    used.append((start, start+duration))
            self.assertEqual(len(used), 1)
            self.assertLess(used[0][0], 20)
            self.assertGreater(used[0][1], 23)
            self.assertEqual(gets[FEED], 3)
            self.assertTrue(all(n == 1 for url, n in gets.items() if url != FEED))
