import base64
from array import array
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from short_render import live_evidence, render_live


class LiveEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
    def test_live_export_preserves_audible_source_audio_at_the_selected_time(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder / "source.mkv"
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                "testsrc2=size=160x90:rate=10:duration=4","-f","lavfi","-i",
                "aevalsrc=if(lt(t\\,2)\\,0\\,0.1*sin(2*PI*880*t)):s=48000:d=4",
                "-c:v","ffv1","-c:a","pcm_s16le",str(source)],check=True)
            output=render_live(source,(1,3),folder,{"credit":"Ad | Test","user":"test"},
                {"hook":"Test the source sound","cta":"Would you watch this?","facecam":{"x":0,"y":0,"w":.3,"h":.5}})
            samples=array("f",subprocess.check_output(["ffmpeg","-v","error","-i",str(output),
                "-vn","-ac","1","-ar","48000","-f","f32le","-"]))
            rms=lambda values:(sum(x*x for x in values)/len(values))**.5
            self.assertLess(rms(samples[9600:33600]),.001)
            self.assertGreater(rms(samples[57600:81600]),.02)
            self.assertLess(max(abs(x) for x in samples),.98)
            self.assertAlmostEqual(len(samples)/48000,2,delta=.05)
            background=subprocess.check_output(["ffmpeg","-v","error","-ss","0.5","-i",str(output),
                "-frames:v","1","-vf","crop=16:16:8:1170,format=rgb24","-f","rawvideo","-"])
            self.assertEqual(len(background),16*16*3)
            self.assertLessEqual(max(background),8)
            with self.assertRaisesRegex(ValueError,"Silent live export"):
                render_live(source,(0,1),folder,{"credit":"Ad | Test","user":"test"},
                    {"hook":"Silent source","cta":"Would you watch this?","facecam":{"x":0,"y":0,"w":.3,"h":.5}})

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

