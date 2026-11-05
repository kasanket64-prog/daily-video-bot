"""Choose a fresh Short from a ranked shortlist and saved draft history."""
import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import unicodedata


def normalized(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join("".join(
        char if unicodedata.category(char)[0] in "LMN" else " "
        for char in text
    ).split())


def select_short(candidates, history):
    """History is oldest first. Candidates are ordered by trend rank."""
    fields = ("source_id", "story", "hook", "category")
    for entry in (*history, *candidates):
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str) or not normalized(entry[field])
            for field in fields
        ):
            raise ValueError("Each entry needs a source_id, story, hook and category")

    used_sources = {entry["source_id"].strip() for entry in history}
    recent_text = [
        (normalized(entry["story"]), normalized(entry["hook"]))
        for entry in history
    ]
    last_category = normalized(history[-1]["category"]) if history else None
    same_category = None
    for candidate in candidates:
        if candidate["source_id"].strip() in used_sources:
            continue
        story, hook = normalized(candidate["story"]), normalized(candidate["hook"])
        # shortcut: wording similarity misses substantial paraphrases, add semantic review if near duplicates recur.
        if any(
            SequenceMatcher(None, story, old_story).ratio() >= 0.85
            or SequenceMatcher(None, hook, old_hook).ratio() >= 0.85
            for old_story, old_hook in recent_text
        ):
            continue
        if normalized(candidate["category"]) != last_category:
            return candidate
        if same_category is None:
            same_category = candidate
    return same_category


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path, help="JSON array sorted by trend rank")
    parser.add_argument("history", type=Path, help="JSON array of drafts, oldest first")
    args = parser.parse_args()
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    history = json.loads(args.history.read_text(encoding="utf-8"))
    if not isinstance(candidates, list) or not isinstance(history, list):
        parser.error("Candidates and history must be JSON arrays")
    print(json.dumps(select_short(candidates, history), ensure_ascii=True))
