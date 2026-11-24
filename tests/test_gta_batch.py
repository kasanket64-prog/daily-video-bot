import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from gta_batch import edit
from short_render import gameplay_moments, gta_levels, gta_signals, gta_windows


class GtaWindowsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
    def test_batch_editor_renders_hook_and_event_question_on_black_vertical_canvas(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "gameplay.mkv"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=10:duration=4", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=4", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)], check=True)
            output = edit(source, 0, 4, {"credit":"Ad | Creator"}, folder, [],
                {"hook":"That jump went wrong", "cta":"Would you risk that jump?"})
            details = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                "stream=width,height,codec_type:format=duration", "-of", "json", str(output)], text=True)
            result = json.loads(details)
            video = next(stream for stream in result["streams"] if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (720, 1280))
            self.assertAlmostEqual(float(result["format"]["duration"]), 4, delta=.1)
            self.assertTrue((folder / "hook.txt").is_file())
            self.assertTrue((folder / "cta.txt").is_file())

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires FFmpeg")
    def test_combined_scan_preserves_audio_and_motion(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "test stream.mkv"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=96x54:rate=10:duration=6", "-f", "lavfi", "-i",
                            "sine=duration=6", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)], check=True)
            expected = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(source), "-an",
                "-vf", "fps=1,scale=96:54,signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=-",
                "-f", "null", "-"], text=True)
            levels, movement = gta_signals(source)
            self.assertEqual(levels, gta_levels(source))
            self.assertEqual(len(levels), 6)
            self.assertEqual(len(movement), 6)
            self.assertEqual(movement, [float(line.split("=")[1]) for line in expected.splitlines()
                                        if line.startswith("lavfi.signalstats.YDIF=")])

    def test_daily_limit_and_used_windows(self):
        levels = [-45.] * 3600
        for i in range(30, 3500, 40):
            levels[i:i+2] = [-10., -10.]
        starts = gta_windows(levels, 24, used=[25])
        self.assertEqual(len(starts), 40)
        ordered = sorted([25, *starts])
        self.assertTrue(all(b-a >= 24 for a, b in zip(ordered, ordered[1:])))

    def test_quiet_action_and_no_filler(self):
        levels = [-70.] * 100
        self.assertEqual(gta_windows(levels, 24), [])
        motion = [0.] * 100
        motion[50] = 30
        self.assertEqual(gta_windows(levels, 24, movement=motion), [45])
        self.assertEqual(gta_windows(levels, 24, used=[45], movement=motion), [])

    def test_moment_ends_after_activity_and_respects_history(self):
        motion = [0.] * 200
        motion[21] = 40
        motion[60:85] = [30.] * 25
        levels = [-70.] * len(motion)
        spans = gameplay_moments(levels, motion)
        self.assertEqual(spans, [(17, 24), (56, 87)])
        self.assertEqual(gameplay_moments(levels, motion, used=[(82, 108)]), spans[:1])
        self.assertLessEqual(max(b-a for a,b in gameplay_moments([-70.]*300, [30.]*300)), 180)
