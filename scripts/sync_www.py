#!/usr/bin/env python3
"""Sync Python source files from custom_components/kyber/ to custom_components/kyber/www/.

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

# ??  JS FRONTEND FILES ARE NOT SYNCED BY THIS SCRIPT
# The following files must be MANUALLY copied after changes:
#   www/kyber/src/plan-cards-mixin.js  ? custom_components/kyber/www/src/plan-cards-mixin.js
#   www/kyber/src/styles.js            ? custom_components/kyber/www/src/styles.js
#   www/kyber/src/utils-mixin.js       ? custom_components/kyber/www/src/utils-mixin.js
#   www/kyber/src/*.js                 ? custom_components/kyber/www/src/*.js
#   www/kyber/kyber-panel.js           ? custom_components/kyber/www/kyber-panel.js
# Run: Copy-Item www/kyber/src/*.js custom_components/kyber/www/src/ -Force
#      Copy-Item www/kyber/kyber-panel.js custom_components/kyber/www/ -Force
# Files to sync: Python modules + manifest (exclude www/ subdirectory itself)
SYNC_PATTERNS = ["*.py", "manifest.json"]

# Files in www/ that are NOT mirrors of src files (frontend assets)
EXCLUDE_NAMES = {
    "kyber-panel.js",
    "ai-mixin.js",
    "plan-cards-mixin.js",
    "codemirror-bundle.js",
    "icon.png",
    "manifest.json",  # must NOT be in www/ mirror — Hassfest treats it as a second integration
}


def _collect_sync_files() -> list[Path]:
    """Return src files that should be mirrored to www/."""
    files: list[Path] = []
    for pattern in SYNC_PATTERNS:
        for f in SRC.glob(pattern):
            if f.name not in EXCLUDE_NAMES:
                files.append(f)
    return sorted(files)


def sync_files(dry_run: bool = False) -> int:
    """Copy src files to www/. Returns count of files copied."""
    copied = 0
    for src_file in _collect_sync_files():
        dest_file = DEST / src_file.name
        if not dest_file.exists() or not filecmp.cmp(src_file, dest_file, shallow=False):
            if dry_run:
                print(f"  would copy: {src_file.name}")
            else:
                shutil.copy2(src_file, dest_file)
                print(f"  copied: {src_file.name}")
            copied += 1
    return copied


def check_files() -> int:
    """Check that all src files are mirrored. Returns count of out-of-sync files."""
    stale: list[str] = []
    for src_file in _collect_sync_files():
        dest_file = DEST / src_file.name
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
            print(f"www/ mirror is up-to-date ({len(_collect_sync_files())} files)")
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
