import base64
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from short_render import live_evidence


class LiveEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
    def test_complete_evidence_from_a_local_stream_capture(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "stream capture.mkv"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=5:duration=6", "-f", "lavfi", "-i",
                "sine=duration=6", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)], check=True)
            frames, audio = live_evidence(source, 0, 6, width=640)
            self.assertEqual(len(frames), 6)
            self.assertGreater(len(base64.b64decode(audio)), 100)
            image = folder / "frame.jpg"
            image.write_bytes(base64.b64decode(frames[0]))
            details = json.loads(subprocess.check_output(["ffprobe", "-v", "error",
                "-show_streams", "-of", "json", str(image)]))
            self.assertEqual((details["streams"][0]["width"], details["streams"][0]["height"]), (640, 360))
            self.assertTrue(all(base64.b64decode(frame).startswith(b"\xff\xd8") for frame in frames))
