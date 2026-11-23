"""Regression tests for translation files and source encoding.

Background: several translations were committed with every non-ASCII character
replaced by "?" ("Entit?t" for "Entität"), and some Python sources contained
UTF-8 that had been decoded as cp1252 ("â†’" for "→"), which leaked into UI
messages. German and the source files have been repaired; these tests keep
them from regressing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KYBER = ROOT / "custom_components" / "kyber"
TRANSLATIONS = KYBER / "translations"

# Translation files known to be intact. Add a language once it has been restored.
CLEAN_TRANSLATIONS = ["en.json", "nl.json", "de.json"]

# "?" glued to letters or doubled is the replacement character of a lossy encode.
_REPLACEMENT_Q = re.compile(r"[^\W\d_]\?[^\W\d_]|\?\?")
# UTF-8 decoded as cp1252/latin-1, e.g. "â†’" for "→", "ðŸ“" for "📍".
_MOJIBAKE = re.compile(r"Ã[\u0080-¿]|Â[\u0080-¿]|â[\u0080-¿€]|ðŸ")


def _strings(node, path=""):
    """Yield (json_path, value) for every string leaf."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


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


@pytest.mark.parametrize("name", CLEAN_TRANSLATIONS)
def test_clean_translations_have_no_replacement_characters(name: str) -> None:
    data = _load_rejecting_duplicates(TRANSLATIONS / name)
    bad = [(p, v) for p, v in _strings(data) if _REPLACEMENT_Q.search(v) or _MOJIBAKE.search(v)]
    assert bad == []


def test_german_translation_uses_umlauts() -> None:
    data = _load_rejecting_duplicates(TRANSLATIONS / "de.json")
    agents = data["options"]["step"]["init"]["sections"]["agents"]["data"]
    assert agents["narrator_max_batch"] == "Batch-Größe des Erzählers"
    assert data["config"]["error"]["cannot_connect"].startswith("Der KI-Anbieter")
    assert "Prüfen" in data["config"]["error"]["cannot_connect"]


def test_german_translation_covers_all_keys_of_strings_json() -> None:
    base = dict(_strings(_load_rejecting_duplicates(KYBER / "strings.json")))
    de = dict(_strings(_load_rejecting_duplicates(TRANSLATIONS / "de.json")))
    assert sorted(set(base) - set(de)) == []


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
