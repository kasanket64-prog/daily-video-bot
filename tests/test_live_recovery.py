from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import live_service as service


class LiveRecoveryTests(unittest.TestCase):
    def run_job(self, frame_results, render_error=None):
        calls=[]
        def post(job,route,data,content_type="application/json"):
            calls.append((route,data))
            if route=="short-history": return []
            if route=="plan": return {"usable":True,"standout":True,"highlight_type":"escape",
                "title":"The car flips and escapes","hook":"Watch the escape","payoff":"The car flips and escapes",
                "cta":"Would you risk that escape?",
                "facecam":{"x":0,"y":0,"w":.3,"h":.4}}
            if route=="short": return {"id":"2026-11-22-g01-short"}
            return {"passed":True}
        stream={"is_live":True,"uploader_id":"kreekcraft","description":"GTA VI", "id":"322529656795",
            "formats":[{"height":480,"url":"https://example.com/stream.m3u8"}]}
        client=MagicMock()
        client.__enter__.return_value.extract_info.return_value=stream
        job={"batchDay":"2026-11-22","creators":[{"user":"kreekcraft","credit":"Ad | KreekCraft",
            "facts":"Reviewed GTA VI gameplay","campaign":"https://example.com/campaign"}]}
        self.assertTrue(service.lock.acquire(blocking=False))
        with (patch.object(service,"YoutubeDL",return_value=client),patch.object(service,"post",side_effect=post),
              patch.object(service,"ffmpeg"),patch.object(service,"probe",return_value={"format":{"duration":"90"}}),
              patch.object(service.neon,"rank",return_value=[{"start":0,"features":{"motion":.1}},
                                                            {"start":30,"features":{"motion":.1}}]),
              patch.object(service,"live_evidence",side_effect=frame_results),
              patch.object(service,"render_live",return_value=Path("reel.mp4"),side_effect=render_error),
              patch.object(service,"inspection",return_value=(b"inspected video",{"sha256":"1"*64}))):
            service.run(job)
        self.assertFalse(service.lock.locked())
        return calls,service.last_result

    def test_damaged_window_is_skipped_and_next_moment_still_reaches_inspection_and_delivery(self):
        error=subprocess.CalledProcessError(69,["ffmpeg"],stderr=b"Invalid data found when processing input")
        calls,result=self.run_job([error,(["frame"]*6,"audio")])
        self.assertEqual(result["state"],"complete")
        self.assertEqual(result["damaged_windows"],1)
        self.assertEqual(result["delivered"],1)
        self.assertEqual(sum(route.startswith("inspect/") for route,_ in calls),1)
        self.assertEqual(sum(route.startswith("preview/") for route,_ in calls),1)

    def test_output_render_failure_is_reported_instead_of_being_skipped_as_bad_input(self):
        error=subprocess.CalledProcessError(1,["ffmpeg"],stderr=b"Encoder failed")
        calls,result=self.run_job([(["frame"]*6,"audio")],render_error=error)
        self.assertEqual(result["state"],"failed")
        self.assertEqual(result["stage"],"render")
        self.assertFalse(any(route.startswith("preview/") for route,_ in calls))
