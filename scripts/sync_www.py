#!/usr/bin/env python3
"""Sync JS frontend files to custom_components/kyber/www/ mirror.

Syncs:
  - JS panel entry:  www/kyber/kyber-panel.js → www/kyber-panel.js
  - JS src files:    www/kyber/src/*.js        → www/src/*.js

Python source files are NOT mirrored — HA only loads Python from
custom_components/kyber/*.py directly; the www/ directory is served as
static files to the browser (JS only).

Run normally to copy all files:
    python scripts/sync_www.py

Run with --check to verify mirrors are up-to-date (CI mode):
    python scripts/sync_www.py --check
"""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "custom_components" / "kyber"
DEST = SRC / "www"

# JS frontend source root
JS_SRC = ROOT / "www" / "kyber"


def _collect_sync_files() -> list[tuple[Path, Path]]:
    """Return (src, dest) pairs for all JS files that should be mirrored to www/."""
    pairs: list[tuple[Path, Path]] = []

    # JS panel entry: www/kyber/kyber-panel.js → www/kyber-panel.js
    panel = JS_SRC / "kyber-panel.js"
    if panel.exists():
        pairs.append((panel, DEST / "kyber-panel.js"))

    # JS src files: www/kyber/src/*.js → www/src/*.js
    js_src_dir = JS_SRC / "src"
    if js_src_dir.exists():
        for f in sorted(js_src_dir.glob("*.js")):
            pairs.append((f, DEST / "src" / f.name))

    return pairs


def sync_files(dry_run: bool = False) -> int:
    """Copy JS src files to www/. Returns count of files copied."""
    copied = 0
    for src_file, dest_file in _collect_sync_files():
        if not dest_file.exists() or not filecmp.cmp(src_file, dest_file, shallow=False):
            if dry_run:
                print(f"  would copy: {src_file.name}")
            else:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)
                print(f"  copied: {src_file.name}")
            copied += 1
    return copied


def check_files() -> int:
    """Check that all JS src files are mirrored. Returns count of out-of-sync files."""
    stale: list[str] = []
    for src_file, dest_file in _collect_sync_files():
        if not dest_file.exists():
            stale.append(f"  MISSING: {src_file.name}")
        elif not filecmp.cmp(src_file, dest_file, shallow=False):
            stale.append(f"  STALE:   {src_file.name}")
    if stale:
        print("www/ mirror is OUT OF SYNC:")
        for line in stale:
            print(line)
        print()
        print("Fix with: python scripts/sync_www.py")
    return len(stale)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Check sync status (CI mode, no writes)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied without writing")
    args = parser.parse_args()

    if args.check:
        stale = check_files()
        if stale == 0:
            total = len(_collect_sync_files())
            print(f"www/ mirror is up-to-date ({total} JS files)")
        sys.exit(1 if stale else 0)
    else:
        copied = sync_files(dry_run=args.dry_run)
        total = len(_collect_sync_files())
        action = "would copy" if args.dry_run else "copied"
        if copied == 0:
            print(f"www/ mirror already up-to-date ({total} JS files)")
        else:
            print(f"{action} {copied}/{total} JS files to www/")


if __name__ == "__main__":
    main()



def sync_files(dry_run: bool = False) -> int:
    """Copy src files to www/. Returns count of files copied."""
    copied = 0
    for src_file, dest_file in _collect_sync_files():
        if not dest_file.exists() or not filecmp.cmp(src_file, dest_file, shallow=False):
            if dry_run:
                print(f"  would copy: {src_file.name}")
            else:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)
                print(f"  copied: {src_file.name}")
            copied += 1
    return copied


def check_files() -> int:
    """Check that all src files are mirrored. Returns count of out-of-sync files."""
    stale: list[str] = []
    for src_file, dest_file in _collect_sync_files():
        if not dest_file.exists():
            stale.append(f"  MISSING: {src_file.name}")
        elif not filecmp.cmp(src_file, dest_file, shallow=False):
            stale.append(f"  STALE:   {src_file.name}")
    if stale:
        print("www/ mirror is OUT OF SYNC:")
        for line in stale:
            print(line)
        print()
        print("Fix with: python scripts/sync_www.py")
    return len(stale)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Check sync status (CI mode, no writes)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied without writing")
    args = parser.parse_args()

    if args.check:
        stale = check_files()
        if stale == 0:
            total = len(_collect_sync_files())
            print(f"www/ mirror is up-to-date ({total} files)")
        sys.exit(1 if stale else 0)
    else:
        copied = sync_files(dry_run=args.dry_run)
        total = len(_collect_sync_files())
        action = "would copy" if args.dry_run else "copied"
        if copied == 0:
            print(f"www/ mirror already up-to-date ({total} files)")
        else:
            print(f"{action} {copied}/{total} files to www/")


if __name__ == "__main__":
    main()
