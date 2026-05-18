#!/usr/bin/env python3
"""Release helper — auto-increments version from last git tag and publishes.

Usage:
    python scripts/release.py                  # patch bump (0.1.108 → 0.1.109)
    python scripts/release.py --minor          # minor bump (0.1.108 → 0.2.0)
    python scripts/release.py --version 1.0.0  # explicit version

Steps performed:
  1. Read last semver tag from git (e.g. v0.1.108)
  2. Increment version (patch by default)
  3. Write new version into manifest.json
  4. git commit "chore: release vX.Y.Z"
  5. git tag vX.Y.Z
  6. git push --no-verify + git push --no-verify origin vX.Y.Z
  7. Create GitHub release via API

Set GITHUB_TOKEN env var (or edit TOKEN below) for the GitHub release step.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "custom_components" / "kyber" / "manifest.json"
REPO = "pgroene/kyber"
# Token is read from GITHUB_TOKEN environment variable at runtime.


def run(cmd: list[str], check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def last_git_version() -> tuple[int, int, int]:
    """Return (major, minor, patch) of the most recent semver tag, or 0.1.0."""
    raw = run(["git", "tag", "--list", "v*", "--sort=-version:refname"], check=False)
    for line in raw.splitlines():
        m = re.match(r"v(\d+)\.(\d+)\.(\d+)$", line.strip())
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return 0, 1, 0


def parse_args():
    p = argparse.ArgumentParser(description="Kyber release helper")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--minor", action="store_true", help="Minor bump")
    group.add_argument("--major", action="store_true", help="Major bump")
    group.add_argument("--version", help="Explicit version (e.g. 1.2.3)")
    p.add_argument("--dry-run", action="store_true", help="Print what would happen, don't act")
    return p.parse_args()


def main():
    args = parse_args()

    if args.version:
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", args.version)
        if not m:
            print(f"Invalid version: {args.version}", file=sys.stderr)
            sys.exit(1)
        new_ver = args.version
    else:
        major, minor, patch = last_git_version()
        if args.major:
            major, minor, patch = major + 1, 0, 0
        elif args.minor:
            minor, patch = minor + 1, 0
        else:
            patch += 1
        new_ver = f"{major}.{minor}.{patch}"

    tag = f"v{new_ver}"
    print(f"Releasing {tag} …")

    # Check working tree is clean (except manifest.json which we'll write)
    dirty = run(["git", "status", "--porcelain"], check=False)
    dirty_lines = [l for l in dirty.splitlines() if not l.strip().endswith("manifest.json")]
    if dirty_lines:
        print("Working tree is dirty (non-manifest changes). Commit or stash first:", file=sys.stderr)
        for l in dirty_lines:
            print(" ", l, file=sys.stderr)
        sys.exit(1)

    # Write manifest.json
    manifest = json.loads(MANIFEST.read_text())
    old_ver = manifest.get("version", "?")
    manifest["version"] = new_ver
    if not args.dry_run:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  manifest.json: {old_ver} → {new_ver}")

    # Sync www mirror
    if not args.dry_run:
        run([sys.executable, str(ROOT / "scripts" / "sync_www.py")])
        print("  www/ synced")

    if args.dry_run:
        print(f"  [dry-run] would commit, tag {tag}, push, create GitHub release")
        return

    # Commit + tag + push
    run(["git", "add", str(MANIFEST), str(ROOT / "custom_components" / "kyber" / "www" / "manifest.json")])
    run(["git", "commit", "-m", f"chore: release {tag}\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"])
    run(["git", "tag", tag])
    run(["git", "push", "--no-verify"])
    run(["git", "push", "--no-verify", "origin", tag])
    print(f"  pushed {tag}")

    # GitHub release
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        import urllib.request
        payload = json.dumps({
            "tag_name": tag,
            "name": tag,
            "body": f"Release {tag}",
            "draft": False,
            "prerelease": False,
        }).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases",
            data=payload,
            headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                release = json.loads(resp.read())
            print(f"  GitHub release: {release['html_url']}")
        except Exception as e:
            print(f"  GitHub release failed (tag pushed OK): {e}", file=sys.stderr)
    else:
        print("  (no GITHUB_TOKEN — skipped GitHub release)")

    print(f"\n✅ {tag} released successfully")


if __name__ == "__main__":
    main()
