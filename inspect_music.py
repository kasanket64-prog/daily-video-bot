"""Transcribe an existing music artifact; never generate or publish media."""
import argparse
import json
from pathlib import Path
import re


def words(text):
    return re.findall(r"[a-z]+", text.lower())


def main():
    from faster_whisper import WhisperModel
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("music-inspection-output"))
    args = parser.parse_args()
    audio_files = list(args.audio_dir.glob("*.wav"))
    if len(audio_files) != 1:
        raise ValueError("Expected exactly one WAV in the existing benchmark artifact")
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_files[0]), language="en", beam_size=5,
                                  word_timestamps=True, vad_filter=False,
                                  condition_on_previous_text=False)
    spans = [{"start": s.start, "end": s.end, "text": s.text,
              "words": [{"text": w.word, "start": w.start, "end": w.end,
                         "probability": w.probability} for w in (s.words or [])]}
             for s in segments]
    expected = "Wings go up, wings go down, Little Pip stays on the ground."
    transcript = " ".join(s["text"].strip() for s in spans)
    report = {"expected": expected, "transcript": transcript, "segments": spans,
              "exact_normalized_match": words(transcript) == words(expected),
              "status": "requires_human_listening",
              "limitation": "ASR can mishear singing; this does not verify musical quality or lip sync."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "lyrics-inspection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
