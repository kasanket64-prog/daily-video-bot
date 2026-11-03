import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import unittest
from unittest.mock import patch, Mock
import urllib.request
import zipfile
import bot


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.job = {"status": "pending", "message_id": 42,
                    "expires": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        self.callback = {"data": "approve:2026-11-03", "from": {"id": 7},
                         "message": {"message_id": 42, "chat": {"id": 7, "type": "private"}}}

    def test_owner_approval_and_repeated_click(self):
        jobs = {"2026-11-03": self.job}
        self.assertTrue(bot.transition(self.callback, jobs, "7", "7"))
        self.assertEqual(self.job["status"], "approved")
        self.assertFalse(bot.transition(self.callback, jobs, "7", "7"))

    def test_rejection_never_approves(self):
        self.callback["data"] = "reject:2026-11-03"
        bot.transition(self.callback, {"2026-11-03": self.job}, 7, 7)
        self.assertEqual(self.job["status"], "rejected")

    def test_wrong_user_chat_message_and_expiry(self):
        for key in ("user", "chat", "message", "group", "expired"):
            with self.subTest(key=key):
                cb, job = copy.deepcopy(self.callback), copy.deepcopy(self.job)
                if key == "user": cb["from"]["id"] = 8
                if key == "chat": cb["message"]["chat"]["id"] = 8
                if key == "message": cb["message"]["message_id"] = 43
                if key == "group": cb["message"]["chat"]["type"] = "group"
                if key == "expired": job["expires"] = "2000-01-01T00:00:00+00:00"
                self.assertFalse(bot.transition(cb, {"2026-11-03": job}, 7, 7))

    def test_unknown_or_malformed_callback(self):
        for value in ("approve:missing", "delete:2026-11-03", "approve", ""):
            self.callback["data"] = value
            self.assertFalse(bot.transition(self.callback, {"2026-11-03": self.job}, 7, 7))


class PublishingTests(unittest.TestCase):
    def job(self):
        return {"status": "approved", "expires": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}

    @patch("bot.notify")
    @patch("bot.instagram", return_value="ig1")
    @patch("bot.youtube", return_value="yt1")
    @patch("bot.artifact", return_value=(b"video", {}))
    @patch("bot.platform_ready", return_value=True)
    def test_independent_platform_success_and_no_duplicate(self, ready, artifact, yt, ig, notify):
        job, store = self.job(), Mock()
        bot.publish(store, job)
        bot.publish(store, job)
        self.assertEqual(job["status"], "published")
        yt.assert_called_once()
        ig.assert_called_once()

    @patch("bot.notify")
    @patch("bot.instagram", side_effect=TimeoutError)
    @patch("bot.youtube", return_value="yt1")
    @patch("bot.artifact", return_value=(b"video", {}))
    @patch("bot.platform_ready", return_value=True)
    def test_partial_failure_not_retried(self, ready, artifact, yt, ig, notify):
        job, store = self.job(), Mock()
        bot.publish(store, job)
        bot.publish(store, job)
        self.assertEqual(job["platforms"]["instagram"]["status"], "needs_review")
        self.assertEqual(job["platforms"]["youtube"]["id"], "yt1")
        yt.assert_called_once()
        ig.assert_called_once()

    @patch("bot.notify")
    @patch("bot.youtube")
    @patch("bot.artifact", return_value=(b"video", {}))
    @patch("bot.platform_ready", side_effect=lambda p: p == "youtube")
    def test_interrupted_upload_stays_stopped(self, ready, artifact, yt, notify):
        job = self.job()
        job["platforms"] = {"youtube": {"status": "started"}}
        bot.publish(Mock(), job)
        yt.assert_not_called()

    @patch("bot.artifact")
    def test_unapproved_never_downloads_or_uploads(self, artifact):
        for status in ("ready", "pending", "rejected", "expired"):
            job = self.job()
            job["status"] = status
            bot.publish(Mock(), job)
        artifact.assert_not_called()

    @patch("bot.github")
    def test_changed_artifact_rejected(self, github):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("video.mp4", b"modified")
            archive.writestr("metadata.json", "{}")
        github.return_value = (stream.getvalue(), {})
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo"}):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                bot.artifact({"artifact_id": 1, "sha256": hashlib.sha256(b"original").hexdigest()})

    @patch("bot.github")
    def test_changed_caption_rejected_even_when_video_matches(self, github):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("video.mp4", b"video")
            archive.writestr("metadata.json", '{"title":"changed"}')
        github.return_value = (stream.getvalue(), {})
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo"}):
            with self.assertRaisesRegex(RuntimeError, "metadata checksum"):
                bot.artifact({"artifact_id": 1, "sha256": hashlib.sha256(b"video").hexdigest(),
                              "metadata_sha256": hashlib.sha256(b"{}").hexdigest()})

    @patch("bot.notify")
    @patch("bot.platform_ready", return_value=False)
    @patch("bot.artifact")
    def test_missing_connections_notified_only_once(self, artifact, ready, notify):
        job, store = self.job(), Mock()
        bot.publish(store, job)
        bot.publish(store, job)
        notify.assert_called_once()
        artifact.assert_not_called()


class GenerationTests(unittest.TestCase):
    def script(self):
        return {"title": "A topic", "description": "A description", "language": "hi",
                "script": "A sufficiently long original spoken script.", "terms": ["space"], "trend_index": 0}

    def test_bad_ai_fields_rejected_before_rendering(self):
        for field, value in (("title", 5), ("title", "x" * 101), ("description", None),
                             ("script", []), ("trend_index", True), ("terms", [42]),
                             ("terms", [""]), ("language", "unknown")):
            with self.subTest(field=field, value=value):
                script = self.script()
                script[field] = value
                with self.assertRaises(RuntimeError):
                    bot.validate_script(script, 1)
        self.assertEqual(bot.validate_script(self.script(), 1)["language"], "hi")

    @patch("bot.workflow_output")
    @patch("bot.Store")
    def test_generation_rerun_is_clean_skip(self, store_type, output):
        day = bot.now().astimezone(bot.IST).date().isoformat()
        store_type.return_value.data = {"jobs": {day: {"status": "ready"}}}
        bot.generate()
        output.assert_called_once_with("generated", "false")

    @patch.dict("os.environ", {"GITHUB_RUN_ID": "123"})
    @patch("bot.github", return_value={"artifacts": [{"name": "preview-123", "id": 99}]})
    @patch("bot.Store")
    def test_register_uses_run_identity_across_midnight(self, store_type, github):
        job = {"status": "generating", "run_id": "123", "sha256": "checksum"}
        store = store_type.return_value
        store.repo = "owner/repo"
        store.data = {"jobs": {"2000-01-01": job}}
        bot.register()
        self.assertEqual(job["artifact_id"], 99)
        self.assertEqual(job["status"], "ready")


class TransportTests(unittest.TestCase):
    def test_bearer_token_not_forwarded_to_artifact_storage(self):
        request = urllib.request.Request("https://api.github.com/archive", headers={"Authorization": "Bearer secret"})
        redirect = bot.SafeRedirect().redirect_request(request, None, 302, "Found", {}, "https://storage.example/video")
        self.assertIsNone(redirect.get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
