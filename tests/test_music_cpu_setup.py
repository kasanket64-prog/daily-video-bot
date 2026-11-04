import unittest
from music_cpu_setup import cpu_dependencies


class CpuDependenciesTest(unittest.TestCase):
    def test_keeps_common_packages_and_excludes_accelerator_backends(self):
        specs = ["torch==2.10.0+cu128; sys_platform == 'linux'", "torchao>=0.16",
                 "nano-vllm; sys_platform != 'darwin'", "mlx-lm>=0.20",
                 "transformers>=4.51,<4.58", "soundfile>=0.13", "uvicorn[standard]>=0.27"]
        self.assertEqual(cpu_dependencies({"project": {"dependencies": specs}}), specs[4:])


if __name__ == "__main__":
    unittest.main()
