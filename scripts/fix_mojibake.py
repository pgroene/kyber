"""Fix cp1252-decoded UTF-8 mojibake in Python source files.

When UTF-8 text is mistakenly decoded as Windows-1252 and stored,
each original UTF-8 byte sequence becomes a sequence of cp1252 characters.
This script reverses that by encoding each suspicious character sequence
back through cp1252 and decoding as UTF-8.
"""
import sys
import re


def _encode_as_high_byte(ch: str) -> int | None:
    """Return the cp1252/latin-1 byte value (>= 0x80) for ch, or None."""
    # Try cp1252 first (handles smart quotes, em-dashes, arrows etc.)
    try:
        b = ch.encode("cp1252")
        if len(b) == 1 and b[0] >= 0x80:
            return b[0]
    except UnicodeEncodeError:
        pass
    # Fall back to latin-1 for C1 control chars (U+0080–U+009F) that cp1252 doesn't map
    try:
        b = ch.encode("latin-1")
        if len(b) == 1 and b[0] >= 0x80:
            return b[0]
    except UnicodeEncodeError:
        pass
    return None


def _is_high_byte_char(ch: str) -> bool:
    return _encode_as_high_byte(ch) is not None


def fix_segment(chars: str) -> str:
    """Try to fix a sequence of high-codepoint characters as cp1252/latin1 → UTF-8."""
    # Build the raw bytes using the best encoding for each char
    try:
        raw = bytes(_encode_as_high_byte(c) for c in chars)
        return raw.decode("utf-8")
    except (TypeError, UnicodeDecodeError):
        return chars


def _is_cp1252_high(ch: str) -> bool:
    """Return True if ch encodes as a single byte >= 0x80 in cp1252."""
    try:
        b = ch.encode("cp1252")
        return len(b) == 1 and b[0] >= 0x80
    except UnicodeEncodeError:
        return False


def fix_mojibake(text: str) -> str:
    """Fix all cp1252-decoded UTF-8 sequences in text."""
    result = []
    i = 0
    while i < len(text):
        if _is_high_byte_char(text[i]):
            j = i + 1
            while j < len(text) and _is_high_byte_char(text[j]):
                j += 1
            segment = text[i:j]
            fixed = fix_segment(segment)
            result.append(fixed)
            i = j
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def process_file(path: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    fixed = fix_mojibake(original)

    if fixed == original:
        print(f"  No changes: {path}")
        return

    # Count fixes
    import difflib
    diffs = list(difflib.unified_diff(original.splitlines(), fixed.splitlines(), lineterm=""))
    changed = sum(1 for l in diffs if l.startswith("-") and not l.startswith("---"))
    print(f"  Fixed {changed} line(s) in {path}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(fixed)


if __name__ == "__main__":
    files = sys.argv[1:] or ["custom_components/kyber/http_api.py"]
    for f in files:
        process_file(f)
    print("Done.")
