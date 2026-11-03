from pathlib import Path
import tempfile
import unittest
from creative import caption_font


class CreativeTests(unittest.TestCase):
    def test_english_captions_never_use_the_devanagari_only_font(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('NotoSans-Bold.ttf', 'NotoSansDevanagari-Bold.ttf'):
                (root / name).touch()
            self.assertEqual(caption_font('en', root).name, 'NotoSans-Bold.ttf')
            self.assertEqual(caption_font('hi', root).name, 'NotoSansDevanagari-Bold.ttf')
