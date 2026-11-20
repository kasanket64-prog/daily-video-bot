import unittest

from short_render import gameplay_moments, gta_windows


class GtaWindowsTests(unittest.TestCase):
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
