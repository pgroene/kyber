#!/usr/bin/env python3
"""Prepend a new version section to CHANGELOG.md when a release tag is pushed.

Usage:
    python scripts/update_changelog.py v0.5.5
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


CHANGELOG = Path("CHANGELOG.md")

SECTION_ORDER = ["Added", "Fixed", "Security", "Changed", "Performance", "Other"]


def run(cmd: list[str], check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result.stdout.strip()


def previous_tag(new_tag: str) -> str | None:
    tags = run(["git", "tag", "--sort=-version:refname"]).splitlines()
    tags = [t.strip() for t in tags if t.strip()]
    try:
        idx = tags.index(new_tag)
        return tags[idx + 1] if idx + 1 < len(tags) else None
    except ValueError:
        return None


def commits_since(prev: str | None, new_tag: str) -> list[str]:
    ref = f"{prev}..{new_tag}" if prev else new_tag
    out = run(["git", "log", "--pretty=format:%s", ref], check=False)
    return [line.strip() for line in out.splitlines() if line.strip()]


def tag_date(tag: str) -> str:
    raw = run(["git", "log", "-1", "--pretty=format:%ai", tag])
    if raw:
        parts = raw.split()
        return f"{parts[0]} {parts[1][:5]} {parts[2]}"
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M %z")


def categorize(commits: list[str]) -> dict[str, list[str]]:
    cats: dict[str, list[str]] = {k: [] for k in SECTION_ORDER}

    skip = re.compile(r"^(chore: bump version|chore: release v|Merge (pull request|branch))", re.I)
    feat = re.compile(r"^feat[:(]", re.I)
    fix_ = re.compile(r"^fix[:(]", re.I)
    sec_ = re.compile(r"^security[:(]|path traversal|xss|injection", re.I)
    perf = re.compile(r"^perf[:(]|compress|performance", re.I)
    chng = re.compile(r"^(refactor|chore|docs|ci|test)[:(]", re.I)

    for msg in commits:
        if skip.match(msg):
            continue
        body = msg.split(":", 1)[1].strip() if ":" in msg else msg
        if sec_.search(msg):
            cats["Security"].append(body)
        elif feat.match(msg):
            cats["Added"].append(body)
        elif fix_.match(msg):
            cats["Fixed"].append(body)
        elif perf.match(msg):
            cats["Performance"].append(body)
        elif chng.match(msg):
            cats["Changed"].append(body)
        else:
            cats["Other"].append(body)

    return {k: v for k, v in cats.items() if v}


def build_section(tag: str, commits: list[str]) -> str:
    version = tag.lstrip("v")
    date = tag_date(tag)
    cats = categorize(commits)

    lines = [f"## [{version}] — {date}", ""]
    for name in SECTION_ORDER:
        items = cats.get(name, [])
        if items:
            lines.append(f"### {name}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines)


def prepend_section(section: str) -> None:
    existing = CHANGELOG.read_text(encoding="utf-8")
    # Insert after header lines (everything before the first "## [")
    pos = existing.find("\n## [")
    if pos == -1:
        updated = existing.rstrip() + "\n\n" + section
    else:
        updated = existing[: pos + 1] + "\n" + section + existing[pos + 1 :]
    CHANGELOG.write_text(updated, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: update_changelog.py <tag>")
        sys.exit(1)

    tag = sys.argv[1]
    version = tag.lstrip("v")

    existing = CHANGELOG.read_text(encoding="utf-8")
    if f"## [{version}]" in existing:
        print(f"CHANGELOG already contains [{version}] — nothing to do.")
        sys.exit(0)

    prev = previous_tag(tag)
    commits = commits_since(prev, tag)

    if not commits:
        print(f"No commits found between {prev!r} and {tag!r}.")
        sys.exit(0)

    section = build_section(tag, commits)
    prepend_section(section)
    print(f"CHANGELOG.md updated with section for {tag}.")
    print(section)


if __name__ == "__main__":
    main()
