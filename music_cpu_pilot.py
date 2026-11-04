"""One bounded ACE-Step CPU experiment; no API keys or publishing."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import time


LYRICS = ("[Verse]\nWings go up, wings go down,\nLittle Pip stays on the ground.\n"
          "[Chorus]\nWings go up, wings go down,\nLittle Pip stays on the ground.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("music-pilot-output"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"status": "failed", "device": "cpu", "lyrics": LYRICS,
              "requested_seconds": 20, "lyric_accuracy": "not checked"}
    try:
        import sys
        sys.path.insert(0, str(args.source.resolve()))
        import torch
        import soundfile as sf
        import numpy as np
        from acestep.handler import AceStepHandler
        from acestep.inference import GenerationParams, GenerationConfig, generate_music

        if torch.cuda.is_available():
            raise RuntimeError("This benchmark must use CPU-only PyTorch.")
        torch.set_num_threads(min(os.cpu_count() or 1, 4))
        report["torch"] = importlib.metadata.version("torch")
        handler = AceStepHandler()
        message, ready = handler.initialize_service(
            project_root=str(args.source.resolve()), config_path="acestep-v15-turbo",
            device="cpu", use_flash_attention=False, compile_model=False,
            use_mlx_dit=False, prefer_source="huggingface",
        )
        if not ready:
            raise RuntimeError(message)
        params = GenerationParams(
            caption="English nursery rhyme sung clearly by one warm adult female lead vocalist. "
                    "Vocals very prominent, every lyric distinctly articulated, simple melody. "
                    "Very quiet glockenspiel accompaniment. Singing starts immediately. "
                    "Sing the verse and chorus exactly as written. No instrumental intro or solo.",
            lyrics=LYRICS, vocal_language="en", bpm=96, duration=20,
            inference_steps=8, thinking=False, use_cot_metas=False,
            use_cot_caption=False, use_cot_lyrics=False, use_cot_language=False,
        )
        config = GenerationConfig(batch_size=1, audio_format="wav",
                                  use_random_seed=False, seeds=[43])
        result = generate_music(handler, None, params, config, save_dir=str(output))
        if not result.success or len(result.audios) != 1:
            raise RuntimeError(result.error or "Expected exactly one generated audio file")
        path = Path(result.audios[0]["path"]).resolve()
        if not path.is_relative_to(output):
            raise RuntimeError("Generated audio is outside the artifact directory")
        samples, rate = sf.read(path, always_2d=True)
        if rate <= 0 or samples.size == 0 or not np.isfinite(samples).all():
            raise RuntimeError("Invalid generated audio")
        duration = len(samples) / rate
        peak = float(np.abs(samples).max())
        if not 19 <= duration <= 21 or peak < 0.0001:
            raise RuntimeError("Output is silent or has unexpected duration")
        report.update(status="generated_unreviewed", audio=path.name,
                      duration=duration, sample_rate=rate, peak=peak)
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
        (output / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
