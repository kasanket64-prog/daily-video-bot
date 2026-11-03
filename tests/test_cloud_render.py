import os
from pathlib import Path
import unittest
from unittest.mock import patch
import cloud_render


class CloudRenderTests(unittest.TestCase):
    def test_worker_origin_must_be_https_without_credentials_or_query(self):
        for value in ("http://example.com", "https://user:password@example.com", "https://example.com/path", "https://example.com?token=secret", ""):
            with patch.dict(os.environ, {"CLOUDFLARE_WORKER_URL": value}):
                with self.assertRaises(RuntimeError):
                    cloud_render.worker_url()
        with patch.dict(os.environ, {"CLOUDFLARE_WORKER_URL": "https://bot.workers.dev/"}):
            self.assertEqual(cloud_render.worker_url(), "https://bot.workers.dev")

    def test_stock_download_cannot_reach_other_hosts_or_local_services(self):
        for url in ("http://cdn.pixabay.com/a.mp4", "https://pixabay.com.attacker.example/a", "http://127.0.0.1/a", "https://user:password@cdn.pixabay.com/a"):
            with self.assertRaises(RuntimeError):
                cloud_render.validate_stock_url(url)
        cloud_render.validate_stock_url("https://cdn.pixabay.com/video/a.mp4")

    def test_active_workflows_do_not_reference_github_secrets(self):
        root = Path(__file__).resolve().parent.parent
        for path in (root / ".github/workflows").glob("*.yml"):
            self.assertNotIn("secrets.", path.read_text(encoding="utf-8"), str(path))
