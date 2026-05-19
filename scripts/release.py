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
    p.add_argument("--github-release-only", metavar="TAG", help="Only create GitHub release for an existing tag (e.g. v0.1.116)")
    return p.parse_args()


def _get_token() -> str:
    """Return GitHub token from env or git remote URL."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    # Fall back to token embedded in git remote URL
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True
        ).stdout.strip()
        m = re.search(r"https://([^@]+)@github\.com", remote)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _build_release_notes(tag: str, prev_tag: str | None) -> str:
    """Generate release notes from git commits between prev_tag and HEAD."""
    if prev_tag:
        log_range = f"{prev_tag}..HEAD"
    else:
        log_range = "HEAD"
    raw = run(
        ["git", "log", log_range, "--pretty=format:%s", "--no-merges"],
        check=False,
    )
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    # Filter out bare chore: release lines
    lines = [l for l in lines if not re.match(r"^chore: release v", l)]

    if not lines:
        return f"Release {tag}"

    # Group by conventional commit type
    groups: dict[str, list[str]] = {"feat": [], "fix": [], "other": []}
    for line in lines:
        if line.startswith("feat"):
            groups["feat"].append(re.sub(r"^feat(\(.+?\))?:\s*", "", line))
        elif line.startswith("fix"):
            groups["fix"].append(re.sub(r"^fix(\(.+?\))?:\s*", "", line))
        else:
            # Skip chore/docs/refactor/test lines to keep notes clean
            if not re.match(r"^(chore|docs|refactor|test|style|ci|build):", line):
                groups["other"].append(line)

    parts: list[str] = []
    if groups["feat"]:
        parts.append("### ✨ What's new\n" + "\n".join(f"- {l}" for l in groups["feat"]))
    if groups["fix"]:
        parts.append("### 🐛 Fixes\n" + "\n".join(f"- {l}" for l in groups["fix"]))
    if groups["other"]:
        parts.append("### 🔧 Other\n" + "\n".join(f"- {l}" for l in groups["other"]))

    if not parts:
        return f"Release {tag}"

    return "\n\n".join(parts)


def main():
    args = parse_args()

    if args.github_release_only:
        tag = args.github_release_only
        if not tag.startswith("v"):
            tag = f"v{tag}"
        token = _get_token()
        if not token:
            print("ERROR: set GITHUB_TOKEN first", file=sys.stderr)
            sys.exit(1)
        import urllib.request
        # Find the tag before this one for release notes range
        all_tags = run(["git", "tag", "--list", "v*", "--sort=-version:refname"], check=False).splitlines()
        tag_idx = next((i for i, t in enumerate(all_tags) if t.strip() == tag), None)
        prev = all_tags[tag_idx + 1].strip() if tag_idx is not None and tag_idx + 1 < len(all_tags) else None
        notes = _build_release_notes(tag, prev)
        headers = {"Authorization": f"token {token}", "Content-Type": "application/json"}
        # Try to find existing release first
        existing_id = None
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/tags/{tag}",
                headers=headers, method="GET",
            )
            with urllib.request.urlopen(req) as resp:
                existing_id = json.loads(resp.read()).get("id")
        except Exception:
            pass
        payload = json.dumps({"tag_name": tag, "name": tag, "body": notes, "draft": False, "prerelease": False}).encode()
        if existing_id:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/{existing_id}",
                data=payload, headers=headers, method="PATCH",
            )
            action = "updated"
        else:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases",
                data=payload, headers=headers, method="POST",
            )
            action = "created"
        with urllib.request.urlopen(req) as resp:
            release = json.loads(resp.read())
        print(f"✅ GitHub release {action}: {release['html_url']}")
        return

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
    # Capture previous tag BEFORE we create the new one (used for release notes)
    prev_version_tag = run(["git", "tag", "--list", "v*", "--sort=-version:refname"], check=False).splitlines()
    prev_version_tag = prev_version_tag[0].strip() if prev_version_tag else None
    print(f"Releasing {tag} …")

    # ── Step 0: JS syntax check ──────────────────────────────────────────────
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_js as _check_js
    js_failures = _check_js.check_all()
    if js_failures:
        print("\n❌ JS syntax check failed — fix errors before releasing:", file=sys.stderr)
        for path, err in js_failures.items():
            print(f"  {path.relative_to(ROOT)}\n{err}", file=sys.stderr)
        sys.exit(1)
    print("  JS syntax OK")

    # Check working tree is clean (except manifest.json which we'll write)
    dirty = run(["git", "status", "--porcelain"], check=False)
    dirty_lines = [l for l in dirty.splitlines()
                   if not l.strip().endswith("manifest.json")
                   and not l.strip().endswith("__init__.py")
                   and not l.strip().endswith("release.py")]
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

    # Bump the JS cache-bust version string in __init__.py (?v=N → ?v=N+1)
    init_file = ROOT / "custom_components" / "kyber" / "__init__.py"
    init_text = init_file.read_text()
    js_ver_match = re.search(r"kyber-panel\.js\?v=(\d+)", init_text)
    if js_ver_match:
        old_js_ver = int(js_ver_match.group(1))
        new_js_ver = old_js_ver + 1
        init_text = re.sub(r"kyber-panel\.js\?v=\d+", f"kyber-panel.js?v={new_js_ver}", init_text)
        if not args.dry_run:
            init_file.write_text(init_text)
        print(f"  kyber-panel.js cache bust: ?v={old_js_ver} → ?v={new_js_ver}")
    else:
        print("  WARNING: could not find kyber-panel.js?v= in __init__.py", file=sys.stderr)

    # Build release notes (also shown in dry-run so you know what's going out)
    notes = _build_release_notes(tag, prev_version_tag)
    print("\n  Release notes:")
    for line in notes.splitlines():
        print(f"    {line}")
    print()

    # Sync www mirror
    if not args.dry_run:
        run([sys.executable, str(ROOT / "scripts" / "sync_www.py")])
        print("  www/ synced")

    if args.dry_run:
        print(f"  [dry-run] would commit, tag {tag}, push, create GitHub release")
        return

    # Commit + tag + push
    files_to_add = [
        str(MANIFEST),
        str(ROOT / "custom_components" / "kyber" / "www" / "manifest.json"),
        str(ROOT / "custom_components" / "kyber" / "__init__.py"),
        str(ROOT / "custom_components" / "kyber" / "www" / "__init__.py"),
    ]
    run(["git", "add"] + files_to_add)
    run(["git", "commit", "-m", f"chore: release {tag}\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"])
    run(["git", "tag", tag])
    run(["git", "push", "--no-verify"])
    run(["git", "push", "--no-verify", "origin", tag])
    print(f"  pushed {tag}")

    # GitHub release
    token = _get_token()
    if token:
        import urllib.request
        payload = json.dumps({
            "tag_name": tag,
            "name": tag,
            "body": notes,
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

