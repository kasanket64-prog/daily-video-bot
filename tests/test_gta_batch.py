import unittest

from short_render import gta_windows


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
