#!/usr/bin/env python3
"""Update the Kyber roadmap issue (#204) based on current GitHub issue state.

Reads all issues, groups them by epic + milestone label, computes their status
(done / shipped / open), and rewrites the roadmap issue body.

Usage:
    python scripts/update_roadmap.py [--dry-run]
        --dry-run   Print the generated markdown but do NOT update the issue.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────────

ROADMAP_ISSUE = 204
REPO = "pgroene/kyber"

# Version order (oldest → newest).  Versions beyond this list land in "Future".
VERSION_ORDER = ["v0.5.7", "v0.5.8", "v0.5.9", "v0.6.0", "v0.7.0"]

VERSION_THEME: dict[str, str] = {
    "v0.5.7": "Memory & Learning",
    "v0.5.8": "Security Foundation + Platform",
    "v0.5.9": "Security Guardrails + HACS",
    "v0.6.0": "Advanced Security + UX Polish",
    "v0.7.0": "AI Expansion",
}

EPIC_LABEL_ORDER = [
    "epic: memory",
    "epic: security",
    "epic: platform",
    "epic: ux",
    "epic: automation",
    "epic: dashboard",
    "epic: ai-expansion",
]

EPIC_LABEL_NAMES: dict[str, str] = {
    "epic: memory":       "Memory & Learning",
    "epic: security":     "Security",
    "epic: platform":     "Platform Maturity",
    "epic: ux":           "UX",
    "epic: automation":   "Automation",
    "epic: dashboard":    "Dashboard",
    "epic: ai-expansion": "AI Expansion",
}

# ── GitHub helpers ─────────────────────────────────────────────────────────────

def gh(*args: str) -> Any:
    """Run a gh CLI command and return parsed JSON."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def fetch_issues() -> list[dict]:
    """Return all issues (open + closed) with labels, milestone, state."""
    return gh(
        "issue", "list",
        "--repo", REPO,
        "--state", "all",
        "--json", "number,title,labels,milestone,state,closedAt,url",
        "--limit", "300",
    )


def fetch_releases() -> list[str]:
    """Return list of published release tag names, newest first."""
    releases = gh("release", "list", "--repo", REPO, "--json", "tagName,isDraft", "--limit", "50")
    return [r["tagName"] for r in releases if not r.get("isDraft")]


# ── Data processing ────────────────────────────────────────────────────────────

def label_names(issue: dict) -> list[str]:
    return [l["name"] for l in issue.get("labels", [])]


def version_labels(issue: dict) -> list[str]:
    return [l for l in label_names(issue) if re.match(r"^v\d+\.\d+", l)]


def epic_labels(issue: dict) -> list[str]:
    return [l for l in label_names(issue) if l.startswith("epic:")]


def is_epic(issue: dict) -> bool:
    return "epic" in label_names(issue)


def group_issues(
    issues: list[dict],
    shipped_versions: set[str],
) -> dict[str, dict[str, list[dict]]]:
    """Group non-epic issues by (version, epic_label).

    Returns:  { version: { epic_label: [issue, ...] } }
    """
    grouped: dict[str, dict[str, list[dict]]] = {v: {} for v in VERSION_ORDER}
    grouped["future"] = {}
    grouped["unversioned"] = {}

    for issue in issues:
        if is_epic(issue):
            continue
        if "roadmap" in label_names(issue):
            continue

        versions = version_labels(issue)
        epics = epic_labels(issue)

        # Assign to the lowest version bucket
        ver = "unversioned"
        for v in VERSION_ORDER:
            if v in versions:
                ver = v
                break
        else:
            if versions:
                ver = "future"

        for epic_lbl in epics or ["(no epic)"]:
            grouped.setdefault(ver, {}).setdefault(epic_lbl, []).append(issue)
        if not epics:
            grouped.setdefault(ver, {}).setdefault("(no epic)", []).append(issue)

    return grouped


# ── Markdown generation ────────────────────────────────────────────────────────

def issue_row(issue: dict, shipped_versions: set[str]) -> str:
    """Single markdown table row for an issue."""
    num = issue["number"]
    title = issue["title"]
    url = issue.get("url", f"https://github.com/{REPO}/issues/{num}")
    state = issue["state"]

    vers = version_labels(issue)
    shipped = state == "CLOSED" or any(v in shipped_versions for v in vers)

    status_icon = "✅" if state == "CLOSED" else ("🚢" if shipped else "📋")
    return f"| {status_icon} | #{num} | [{title}]({url}) |"


def render_version_section(
    ver: str,
    issues_by_epic: dict[str, list[dict]],
    shipped_versions: set[str],
    latest_release: str,
) -> str:
    if not issues_by_epic:
        return ""

    theme = VERSION_THEME.get(ver, ver)
    is_shipped = ver in shipped_versions
    is_current = (ver == latest_release or ver.startswith(latest_release.rstrip("0123456789").rstrip(".")))

    if is_shipped:
        header_icon = "✅"
        status_note = f"**Released** as `{ver}`"
    elif is_current:
        header_icon = "🔄"
        status_note = "**In progress** (current branch)"
    else:
        header_icon = "🗓️"
        status_note = "Planned"

    lines = [
        f"## {header_icon} {ver} — {theme}",
        f"> {status_note} | Epic theme: {theme}",
        "",
    ]

    for epic_lbl in EPIC_LABEL_ORDER + ["(no epic)"]:
        if epic_lbl not in issues_by_epic:
            continue
        epic_issues = issues_by_epic[epic_lbl]
        epic_display = EPIC_LABEL_NAMES.get(epic_lbl, epic_lbl)

        lines.append(f"### {epic_display}")
        lines.append("| | # | Title |")
        lines.append("|---|---|---|")
        for iss in sorted(epic_issues, key=lambda i: i["number"]):
            lines.append(issue_row(iss, shipped_versions))
        lines.append("")

    return "\n".join(lines)


def render_summary_table(
    grouped: dict[str, dict[str, list[dict]]],
    shipped_versions: set[str],
) -> str:
    rows = [
        "## 📊 Summary",
        "",
        "| Version | Theme | Status | Open | Done |",
        "|---------|-------|--------|------|------|",
    ]
    for ver in VERSION_ORDER:
        issues_by_epic = grouped.get(ver, {})
        all_issues = [i for lst in issues_by_epic.values() for i in lst]
        total = len(all_issues)
        done = sum(1 for i in all_issues if i["state"] == "CLOSED")
        theme = VERSION_THEME.get(ver, ver)
        shipped = ver in shipped_versions
        status = "✅ Shipped" if shipped else f"{done}/{total} done"
        rows.append(f"| `{ver}` | {theme} | {status} | {total - done} | {done} |")
    return "\n".join(rows)


def build_roadmap(
    issues: list[dict],
    shipped_versions: set[str],
    latest_release: str,
    generated_at: str,
) -> str:
    grouped = group_issues(issues, shipped_versions)

    parts = [
        "# 🗺️ Kyber Roadmap",
        "",
        f"> Auto-generated on `{generated_at}` from live issue state.  ",
        f"> Latest release: `{latest_release}`.  ",
        "> Legend: ✅ closed · 🚢 version shipped · 📋 open",
        "",
        "---",
        "",
    ]

    for ver in VERSION_ORDER:
        section = render_version_section(
            ver, grouped.get(ver, {}), shipped_versions, latest_release,
        )
        if section:
            parts.append(section)
            parts.append("---")
            parts.append("")

    parts.append(render_summary_table(grouped, shipped_versions))
    parts.append("")
    parts.append("---")
    parts.append(f"_Updated automatically after each release by [`scripts/update_roadmap.py`](../scripts/update_roadmap.py)._")

    return "\n".join(parts)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate Kyber roadmap issue #204")
    parser.add_argument("--dry-run", action="store_true", help="Print markdown without updating")
    args = parser.parse_args()

    print("📥 Fetching issues…", file=sys.stderr)
    issues = fetch_issues()
    print(f"   {len(issues)} issues fetched", file=sys.stderr)

    print("📦 Fetching releases…", file=sys.stderr)
    releases = fetch_releases()
    print(f"   {len(releases)} releases: {releases[:5]}", file=sys.stderr)

    shipped_versions: set[str] = set()
    for tag in releases:
        # Map e.g. v0.5.6 → version label v0.5.6, v0.5.6.1 → v0.5.6 (patch)
        base = re.sub(r"\.\d+$", "", tag) if tag.count(".") > 2 else tag
        for v in VERSION_ORDER:
            if tag.startswith(v) or base == v:
                shipped_versions.add(v)

    latest_release = releases[0] if releases else "unknown"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print("🔨 Building roadmap…", file=sys.stderr)
    body = build_roadmap(issues, shipped_versions, latest_release, generated_at)

    if args.dry_run:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(body)
        return

    print(f"✏️  Updating issue #{ROADMAP_ISSUE}…", file=sys.stderr)
    subprocess.run(
        ["gh", "issue", "edit", str(ROADMAP_ISSUE),
         "--repo", REPO,
         "--body", body],
        check=True,
    )
    print(f"✅ Roadmap issue #{ROADMAP_ISSUE} updated.", file=sys.stderr)


if __name__ == "__main__":
    main()
