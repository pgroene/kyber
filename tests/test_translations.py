"""Regression tests for translation files and source encoding.

Background: some Python sources contained UTF-8 that had been decoded as
cp1252 ("â†’" for "→"), which leaked into UI messages, and a duplicated
chat_timeout key slipped into the options translations. These tests keep both
from coming back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KYBER = ROOT / "custom_components" / "kyber"
TRANSLATIONS = KYBER / "translations"

# UTF-8 decoded as cp1252/latin-1, e.g. "â†’" for "→", "ðŸ“" for "📍".
_MOJIBAKE = re.compile(r"Ã[\u0080-¿]|Â[\u0080-¿]|â[\u0080-¿€]|ðŸ")


def _load_rejecting_duplicates(path: Path) -> dict:
    def _hook(pairs):
        keys = [k for k, _ in pairs]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ValueError(f"duplicate keys {dupes} in {path.name}")
        return dict(pairs)

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_hook)


ALL_TRANSLATION_FILES = sorted(p.name for p in TRANSLATIONS.glob("*.json"))


@pytest.mark.parametrize("name", ["strings.json"] + ALL_TRANSLATION_FILES)
def test_translation_files_have_no_duplicate_keys(name: str) -> None:
    path = KYBER / name if name == "strings.json" else TRANSLATIONS / name
    _load_rejecting_duplicates(path)


def _source_files():
    for pattern in ("*.py", "www/src/*.js", "www/*.js"):
        for path in sorted(KYBER.glob(pattern)):
            if "bundle" not in path.name:
                yield path


@pytest.mark.parametrize("path", list(_source_files()), ids=lambda p: str(p.relative_to(KYBER)))
def test_sources_have_no_mojibake(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    bad = [
        (no, line.strip()[:80])
        for no, line in enumerate(text.splitlines(), 1)
        if _MOJIBAKE.search(line)
    ]
    assert bad == []
