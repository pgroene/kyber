#!/usr/bin/env python3
"""Verify JavaScript files for syntax errors before release.

Strategies (tried in order):
  1. node --check <file>  — full parse, catches all syntax errors
  2. esprima (Python)     — full JS parser, catches all syntax errors
  3. brace-depth fallback — only catches depth-goes-negative (extra }) errors;
                            used only when neither node nor esprima is available.

Only checks source files we own (www/src/*.js + www/kyber-panel.js).
Skips minified bundles and mirror copies.

Usage:
    python scripts/check_js.py                   # check all source JS files
    python scripts/check_js.py path/to/file.js  # check specific file(s)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Only check source files we own — not minified bundles or mirror copies.
JS_SOURCE_FILES = [
    ROOT / "custom_components" / "kyber" / "www" / "kyber-panel.js",
]
JS_SOURCE_DIRS = [
    ROOT / "custom_components" / "kyber" / "www" / "src",
]

_HAS_NODE: bool | None = None
_HAS_ESPRIMA: bool | None = None


def _node_available() -> bool:
    global _HAS_NODE
    if _HAS_NODE is None:
        _HAS_NODE = shutil.which("node") is not None
    return _HAS_NODE


def _esprima_available() -> bool:
    global _HAS_ESPRIMA
    if _HAS_ESPRIMA is None:
        try:
            import esprima  # noqa: F401
            _HAS_ESPRIMA = True
        except ImportError:
            _HAS_ESPRIMA = False
    return _HAS_ESPRIMA


# ---------------------------------------------------------------------------
# node --check
# ---------------------------------------------------------------------------

def _check_with_node(path: Path) -> str | None:
    """Return error string or None if OK."""
    try:
        r = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return (r.stderr or r.stdout).strip()
        return None
    except Exception as e:
        return str(e)


# ---------------------------------------------------------------------------
# esprima (full JS parser, Python package)
# ---------------------------------------------------------------------------

def _preprocess_for_esprima(src: str) -> str:
    """Transpile ES2020+ syntax down to what esprima 4.x understands.

    esprima 4.0 supports ES2019. We have files using ES2020+ features, so we
    do lightweight textual substitutions that preserve structure (which is all
    we care about for syntax checking) without changing semantics significantly.
    """
    import re
    # Logical/nullish assignment (??=  ||=  &&=) → plain assignment
    src = re.sub(r'\?\?=', '=', src)
    src = re.sub(r'\|\|=', '=', src)
    src = re.sub(r'&&=', '=', src)
    # Nullish coalescing (??) → logical OR
    src = re.sub(r'\?\?', '||', src)
    # Optional chaining — order matters: handle ?.[ and ?.( before ?.
    src = re.sub(r'\?\.\[', '[', src)   # obj?.[i]   → obj[i]
    src = re.sub(r'\?\.\(', '(', src)   # func?.()   → func()
    src = re.sub(r'\?\.', '.', src)     # obj?.prop  → obj.prop
    # Optional catch binding: catch { ... } → catch(_e) { ... }
    src = re.sub(r'\bcatch\s*\{', 'catch(_e){', src)
    # Numeric separators: 1_000 → 1000
    while re.search(r'\d_\d', src):
        src = re.sub(r'(\d)_(\d)', r'\1\2', src)
    return src


def _check_with_esprima(path: Path) -> str | None:
    """Return error string or None if OK."""
    import esprima
    src = _preprocess_for_esprima(path.read_text(encoding="utf-8"))
    try:
        esprima.parseModule(src, tolerant=False)
        return None
    except esprima.Error as exc:
        return f"  {exc}"
    except Exception as exc:
        return f"  parse error: {exc}"


# ---------------------------------------------------------------------------
# Fallback: brace-depth checker (last resort)
# ---------------------------------------------------------------------------

def _check_with_braces(path: Path) -> str | None:
    """Very basic fallback: only catches extra } (depth goes negative).

    Strips // and /* */ comments plus template literals, then tracks { } depth.
    Does NOT strip quoted strings — avoids false positives from " or ' inside
    regex character classes like /[&<>"']/. Only reports depth < 0 (not net
    imbalance) so stray { in unstripped strings don't give false positives.
    """
    src = path.read_text(encoding="utf-8")
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        if src[i:i+2] == "/*":
            i += 2
            while i < n and src[i:i+2] != "*/":
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            i += 2
        elif src[i:i+2] == "//":
            while i < n and src[i] != "\n":
                i += 1
        elif src[i] == "`":
            i += 1
            t_depth = 0
            while i < n:
                if src[i] == "\\" and i + 1 < n:
                    i += 2; continue
                if src[i] == "`" and t_depth == 0:
                    i += 1; break
                if src[i:i+2] == "${":
                    i += 2; t_depth += 1; continue
                if src[i] == "}" and t_depth > 0:
                    i += 1; t_depth -= 1; continue
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
        elif src[i] in "{}":
            out.append(src[i]); i += 1
        else:
            out.append("\n" if src[i] == "\n" else " ")
            i += 1

    errors: list[str] = []
    depth = 0
    for lineno, line in enumerate("".join(out).splitlines(), 1):
        for col, ch in enumerate(line, 1):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    errors.append(
                        f"  line {lineno}:{col} — unexpected '}}' "
                        f"(depth went negative)"
                    )
                    depth = 0
    return "\n".join(errors) if errors else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_file(path: Path) -> str | None:
    """Return error message or None if the file is OK."""
    if _node_available():
        return _check_with_node(path)
    if _esprima_available():
        return _check_with_esprima(path)
    return _check_with_braces(path)


def check_all(paths: list[Path] | None = None) -> dict[Path, str]:
    """Check all JS source files; return {path: error} for any that fail."""
    if paths is None:
        paths = list(JS_SOURCE_FILES)
        for d in JS_SOURCE_DIRS:
            if d.exists():
                paths.extend(sorted(d.glob("*.js")))
        seen: set[Path] = set()
        paths = [p for p in paths if not (p in seen or seen.add(p))]

    if _node_available():
        strategy = "node --check"
    elif _esprima_available():
        strategy = "esprima"
    else:
        strategy = "brace-depth fallback"
    print(f"[check_js] strategy: {strategy}")

    failures: dict[Path, str] = {}
    for p in paths:
        if not p.exists():
            continue
        err = check_file(p)
        if err:
            failures[p] = err
        else:
            print(f"  ✅ {p.relative_to(ROOT)}")
    return failures


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else None
    failures = check_all(paths)
    if failures:
        print("\n❌ JS check FAILED:")
        for p, err in failures.items():
            print(f"\n  {p.relative_to(ROOT)}")
            print(err)
        return 1
    print("\n✅ All JS files OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

