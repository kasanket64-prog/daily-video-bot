"""Use upstream dependencies without installing CUDA or GPU-only backends."""
from pathlib import Path
import re
import subprocess
import sys
import tomllib


def cpu_dependencies(project):
    excluded = {"torch", "torchvision", "torchaudio", "torchcodec", "torchao",
                "nano-vllm", "mlx", "mlx-lm"}
    return [spec for spec in project["project"]["dependencies"]
            if re.split(r"[<>=!~;\s\[]", spec, maxsplit=1)[0].lower() not in excluded]


if __name__ == "__main__":
    source = Path(sys.argv[1])
    project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    # shortcut: upstream's torchcodec/torchao imports must stay optional for CPU inference.
    # Verify on the pinned source before upgrading it.
    subprocess.run([sys.executable, "-m", "pip", "install", *cpu_dependencies(project)], check=True)
