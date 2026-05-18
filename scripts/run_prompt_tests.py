#!/usr/bin/env python3
"""Prompt regression test runner for Kyber.

Loads test case directories from tests/prompt_regression/cases/, runs keyword and
intent assertions against stored or freshly-generated responses, records results in
run_history.json, and generates a self-contained report.html.

Usage:
    python scripts/run_prompt_tests.py
    python scripts/run_prompt_tests.py --model local:ollama/mistral
    python scripts/run_prompt_tests.py --cases path/to/cases
    python scripts/run_prompt_tests.py --case-id tc_slaapkamer_001
    python scripts/run_prompt_tests.py --offline   # assertions on stored baseline only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "tests" / "prompt_regression" / "cases"
REPORT_PATH = ROOT / "tests" / "prompt_regression" / "report.html"
MANIFEST_PATH = ROOT / "custom_components" / "kyber" / "manifest.json"

# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def _kyber_version() -> str:
    try:
        return json.loads(MANIFEST_PATH.read_text())["version"]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Test case loading
# ---------------------------------------------------------------------------

def load_test_cases(cases_dir: Path) -> list[dict[str, Any]]:
    """Load all test cases from subdirectories of cases_dir."""
    cases = []
    for case_dir in sorted(cases_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        test_json = case_dir / "test.json"
        if not test_json.exists():
            continue
        try:
            data = json.loads(test_json.read_text(encoding="utf-8"))
            data["_dir"] = case_dir
            cases.append(data)
        except Exception as exc:
            print(f"  ⚠  Skipping {case_dir.name}: {exc}", file=sys.stderr)
    return cases


def load_run_history(case_dir: Path) -> list[dict[str, Any]]:
    hist_path = case_dir / "run_history.json"
    if hist_path.exists():
        try:
            return json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_run_history(case_dir: Path, history: list[dict[str, Any]]) -> None:
    (case_dir / "run_history.json").write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------

def run_assertions(
    response: str,
    intent: str | None,
    tool_calls: list[str],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run all assertions; return list of {type, value, passed, actual}."""
    results: list[dict[str, Any]] = []

    # response_contains
    for kw in expected.get("response_contains", []):
        passed = kw.lower() in response.lower()
        results.append({"type": "response_contains", "value": kw, "passed": passed, "actual": None})

    # response_not_contains
    for kw in expected.get("response_not_contains", []):
        passed = kw.lower() not in response.lower()
        results.append({"type": "response_not_contains", "value": kw, "passed": passed, "actual": None})

    # intent
    if "intent" in expected:
        passed = (intent or "").lower() == expected["intent"].lower()
        results.append({"type": "intent", "value": expected["intent"], "passed": passed, "actual": intent})

    # language (simple heuristic: Dutch has many short words + 'de'/'het'/'een')
    if "language" in expected:
        lang = expected["language"]
        if lang == "nl":
            dutch_markers = ["de ", "het ", "een ", "van ", "met ", "in "]
            detected_nl = sum(1 for m in dutch_markers if m in response.lower()) >= 2
            passed = detected_nl
        else:
            passed = True  # other language checks not implemented
        results.append({"type": "language", "value": lang, "passed": passed, "actual": None})

    # tool_calls_expected
    for expected_tool in expected.get("tool_calls_expected", []):
        passed = any(expected_tool.lower() in tc.lower() for tc in tool_calls)
        results.append({"type": "tool_call", "value": expected_tool, "passed": passed, "actual": None})

    return results


def score(assertion_results: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (passed, total)."""
    passed = sum(1 for r in assertion_results if r["passed"])
    return passed, len(assertion_results)


# ---------------------------------------------------------------------------
# Offline mode: run assertions on baseline response only
# ---------------------------------------------------------------------------

def run_offline(case: dict[str, Any], version: str, model: str) -> dict[str, Any]:
    """Run assertions against the stored baseline_response."""
    baseline = case.get("baseline_response", "")
    intent = case.get("input", {}).get("intent", "")
    tool_log = [t.get("name", "") for t in case.get("input", {}).get("tool_log", [])]
    expected = case.get("expected_output", {})

    t0 = time.monotonic()
    assertion_results = run_assertions(baseline, intent, tool_log, expected)
    latency_ms = int((time.monotonic() - t0) * 1000)

    passed, total = score(assertion_results)
    return {
        "version": version,
        "model": model,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline",
        "score": round(passed / total, 3) if total else 1.0,
        "passed": passed,
        "failed": total - passed,
        "latency_ms": latency_ms,
        "response": baseline,
        "assertion_details": assertion_results,
    }


# ---------------------------------------------------------------------------
# Local Ollama model mode
# ---------------------------------------------------------------------------

def _call_ollama(model_name: str, prompt: str, system: str) -> tuple[str, int]:
    """Call a local Ollama model. Returns (response_text, latency_ms)."""
    try:
        import urllib.request
        payload = json.dumps({
            "model": model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }).encode()
        t0 = time.monotonic()
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        latency_ms = int((time.monotonic() - t0) * 1000)
        return data["message"]["content"], latency_ms
    except Exception as exc:
        return f"[ERROR: {exc}]", 0


def run_with_ollama(case: dict[str, Any], model_name: str, version: str, full_model: str) -> dict[str, Any]:
    """Run test case using a local Ollama model."""
    question = case.get("input", {}).get("question", "")
    system_prompt = case.get("input", {}).get("expanded_prompt", "You are a helpful assistant.")
    expected = case.get("expected_output", {})
    intent = case.get("input", {}).get("intent", "")

    response, latency_ms = _call_ollama(model_name, question, system_prompt)
    assertion_results = run_assertions(response, intent, [], expected)
    passed, total = score(assertion_results)

    return {
        "version": version,
        "model": full_model,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "mode": "ollama",
        "score": round(passed / total, 3) if total else 1.0,
        "passed": passed,
        "failed": total - passed,
        "latency_ms": latency_ms,
        "response": response,
        "assertion_details": assertion_results,
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def _trend_arrow(history: list[dict[str, Any]], current_score: float, version: str) -> str:
    """Compare current score to the previous version's score."""
    prev = [h for h in history if h.get("version") != version]
    if not prev:
        return "🆕"
    prev_score = prev[-1].get("score", 0)
    if current_score > prev_score + 0.05:
        return "↑↑" if current_score - prev_score > 0.2 else "↑"
    if current_score < prev_score - 0.05:
        return "↓↓" if prev_score - current_score > 0.2 else "↓"
    return "→"


def print_score_table(
    results: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]],
    version: str,
    model: str,
) -> None:
    """Print a score table to stdout.

    results: list of (case, run_result, history)
    """
    w_name = max(30, max((len(c.get("label", c.get("id", "?"))) for c, _, _ in results), default=30))
    header = f"{'Test case':<{w_name}}  Score     Trend   ms"
    sep = "─" * len(header)
    print(f"\nKyber v{version} · model: {model}")
    print(sep)
    print(header)
    print(sep)

    total_passed = 0
    total_assertions = 0
    total_ms = 0

    for case, run_result, history in results:
        label = case.get("label", case.get("id", "?"))[:w_name]
        passed = run_result["passed"]
        failed = run_result["failed"]
        total = passed + failed
        total_passed += passed
        total_assertions += total
        total_ms += run_result.get("latency_ms", 0)

        score_str = f"{passed}/{total}"
        icon = "✅" if failed == 0 else ("⚠️ " if failed <= total // 2 else "❌")
        trend = _trend_arrow(history, run_result["score"], version)
        ms = run_result.get("latency_ms", 0)

        print(f"{label:<{w_name}}  {score_str} {icon:<4}  {trend:<6}  {ms}ms")

    print(sep)
    pct = f"{100*total_passed//total_assertions}%" if total_assertions else "—"
    avg_ms = total_ms // len(results) if results else 0
    print(f"{'TOTAL':<{w_name}}  {total_passed}/{total_assertions} {pct:<9}         avg {avg_ms}ms")
    print()


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------

def _generate_html_report(
    all_results: list[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> str:
    """Generate self-contained HTML report with Chart.js visualizations."""
    # Build structured data for the report
    cases_data = []
    for case, history in all_results:
        case_id = case.get("id", "unknown")
        label = case.get("label", case_id)
        # All runs across all versions/models
        runs = []
        for run in history:
            runs.append({
                "version": run.get("version", "?"),
                "model": run.get("model", "?"),
                "ran_at": run.get("ran_at", ""),
                "score": run.get("score", 0),
                "passed": run.get("passed", 0),
                "failed": run.get("failed", 0),
                "latency_ms": run.get("latency_ms", 0),
                "mode": run.get("mode", "?"),
                "response": (run.get("response", "")[:500] + "…") if len(run.get("response", "")) > 500 else run.get("response", ""),
                "assertion_details": run.get("assertion_details", []),
            })
        cases_data.append({
            "id": case_id,
            "label": label,
            "question": case.get("input", {}).get("question", ""),
            "runs": runs,
        })

    data_json = json.dumps(cases_data, ensure_ascii=False)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kyber Prompt Regression Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2e3147;
    --text: #e2e8f0; --muted: #8892a4; --accent: #4f8ef7;
    --green: #22c55e; --yellow: #eab308; --red: #ef4444;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; padding: 24px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 24px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px 24px; min-width: 140px; }}
  .stat-card .val {{ font-size: 2rem; font-weight: 700; }}
  .stat-card .lbl {{ color: var(--muted); font-size: 0.8rem; margin-top: 2px; }}
  .green {{ color: var(--green); }} .yellow {{ color: var(--yellow); }} .red {{ color: var(--red); }}
  .section {{ margin-bottom: 32px; }}
  .section h2 {{ font-size: 1rem; margin-bottom: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }}
  th {{ background: #22253a; padding: 10px 14px; text-align: left; font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  td {{ padding: 10px 14px; border-top: 1px solid var(--border); font-size: 0.9rem; }}
  tr.expandable {{ cursor: pointer; }}
  tr.expandable:hover td {{ background: #1e2133; }}
  tr.detail-row td {{ background: #14172200; padding: 0; }}
  .detail-inner {{ padding: 12px 16px; border-top: 1px solid var(--border); }}
  .detail-inner pre {{ background: #0a0c14; border-radius: 6px; padding: 12px; font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; }}
  .assertions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }}
  .badge {{ padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }}
  .badge.pass {{ background: #16532440; color: var(--green); border: 1px solid var(--green); }}
  .badge.fail {{ background: #7f1d1d40; color: var(--red); border: 1px solid var(--red); }}
  .filters {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }}
  .filter-btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--muted); border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 0.85rem; }}
  .filter-btn.active {{ border-color: var(--accent); color: var(--accent); }}
  select {{ background: var(--surface); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 4px 10px; font-size: 0.85rem; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 32px; }}
  .chart-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  @media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .score-cell {{ font-weight: 600; }}
  .na {{ color: var(--muted); }}
</style>
</head>
<body>
<h1>🧪 Kyber Prompt Regression Report</h1>
<div class="meta">Generated {generated_at}</div>

<div class="summary" id="summary-cards"></div>

<div class="charts">
  <div class="chart-box"><canvas id="trend-chart" height="200"></canvas></div>
  <div class="chart-box"><canvas id="latency-chart" height="200"></canvas></div>
</div>

<div class="section">
  <h2>Test cases</h2>
  <div class="filters">
    <button class="filter-btn active" onclick="setFilter('all')">All</button>
    <button class="filter-btn" onclick="setFilter('fail')">Failing</button>
    <button class="filter-btn" onclick="setFilter('pass')">Passing</button>
    <label style="color:var(--muted);font-size:0.85rem;">Model:
      <select id="model-select" onchange="renderTable()"><option value="">All models</option></select>
    </label>
    <label style="color:var(--muted);font-size:0.85rem;">Version:
      <select id="version-select" onchange="renderTable()"><option value="">Latest</option></select>
    </label>
  </div>
  <div id="table-container"></div>
</div>

<script>
const CASES = {data_json};
let _filter = 'all';

// Collect all versions and models
const versions = [...new Set(CASES.flatMap(c => c.runs.map(r => r.version)))].sort();
const models = [...new Set(CASES.flatMap(c => c.runs.map(r => r.model)))];

function getLastRun(caseData, model, version) {{
  let runs = caseData.runs;
  if (model) runs = runs.filter(r => r.model === model);
  if (version) {{
    runs = runs.filter(r => r.version === version);
  }} else {{
    // latest version
    const maxV = versions[versions.length - 1];
    runs = runs.filter(r => r.version === maxV);
  }}
  return runs[runs.length - 1] || null;
}}

function scoreColor(score) {{
  if (score >= 0.9) return 'green';
  if (score >= 0.6) return 'yellow';
  return 'red';
}}

function trendArrow(caseData, currentRun, selectedVersion) {{
  if (!currentRun) return '';
  const vIdx = versions.indexOf(currentRun.version);
  if (vIdx <= 0) return '🆕';
  const prev = caseData.runs.find(r => r.version === versions[vIdx-1] && r.model === currentRun.model);
  if (!prev) return '🆕';
  const diff = currentRun.score - prev.score;
  if (diff > 0.2) return '↑↑';
  if (diff > 0.05) return '↑';
  if (diff < -0.2) return '↓↓';
  if (diff < -0.05) return '↓';
  return '→';
}}

function setFilter(f) {{
  _filter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.textContent.toLowerCase().startsWith(f === 'all' ? 'all' : f)));
  renderTable();
}}

function renderTable() {{
  const model = document.getElementById('model-select').value;
  const version = document.getElementById('version-select').value;
  const container = document.getElementById('table-container');
  const maxV = versions[versions.length - 1];

  const rows = CASES.map((c, i) => {{
    const run = getLastRun(c, model, version || null);
    const last = run || {{ passed: 0, failed: 0, score: 0, latency_ms: 0 }};
    const total = last.passed + last.failed;
    const pass = last.passed === total && total > 0;
    if (_filter === 'fail' && pass) return null;
    if (_filter === 'pass' && !pass) return null;
    const arr = trendArrow(c, run, version);
    const scoreStr = run ? `${{last.passed}}/${{total}}` : '—';
    const clr = run ? scoreColor(last.score) : 'na';
    return `
      <tr class="expandable" onclick="toggleDetail(${{i}})">
        <td>${{c.label}}</td>
        <td class="score-cell ${{clr}}">${{scoreStr}}</td>
        <td>${{arr}}</td>
        <td>${{run ? last.latency_ms + 'ms' : '—'}}</td>
        <td>${{run ? run.model : '—'}}</td>
        <td>${{run ? run.version : '—'}}</td>
      </tr>
      <tr class="detail-row" id="detail-${{i}}" style="display:none">
        <td colspan="6">
          <div class="detail-inner">
            <div class="assertions" id="ass-${{i}}"></div>
            <pre id="resp-${{i}}"></pre>
          </div>
        </td>
      </tr>`;
  }}).filter(Boolean);

  container.innerHTML = `<table>
    <thead><tr><th>Test case</th><th>Score</th><th>Trend</th><th>Latency</th><th>Model</th><th>Version</th></tr></thead>
    <tbody>${{rows.join('')}}</tbody>
  </table>`;
}}

function toggleDetail(i) {{
  const model = document.getElementById('model-select').value;
  const version = document.getElementById('version-select').value;
  const row = document.getElementById('detail-' + i);
  if (row.style.display !== 'none') {{ row.style.display = 'none'; return; }}
  const run = getLastRun(CASES[i], model, version || null);
  if (!run) return;
  const assEl = document.getElementById('ass-' + i);
  assEl.innerHTML = (run.assertion_details || []).map(a =>
    `<span class="badge ${{a.passed ? 'pass' : 'fail'}}">${{a.passed ? '✅' : '❌'}} ${{a.type}}: ${{a.value}}</span>`
  ).join('');
  document.getElementById('resp-' + i).textContent = run.response || '(no response)';
  row.style.display = '';
}}

function buildSummary() {{
  const maxV = versions[versions.length - 1];
  const latest = CASES.map(c => getLastRun(c, '', null)).filter(Boolean);
  const totalPassed = latest.reduce((s, r) => s + r.passed, 0);
  const totalAll = latest.reduce((s, r) => s + r.passed + r.failed, 0);
  const pct = totalAll ? Math.round(100 * totalPassed / totalAll) : 0;
  const avgMs = latest.length ? Math.round(latest.reduce((s, r) => s + r.latency_ms, 0) / latest.length) : 0;
  const failing = latest.filter(r => r.failed > 0).length;
  document.getElementById('summary-cards').innerHTML = `
    <div class="stat-card"><div class="val ${{pct >= 90 ? 'green' : pct >= 60 ? 'yellow' : 'red'}}">${{pct}}%</div><div class="lbl">Pass rate (${{totalPassed}}/${{totalAll}})</div></div>
    <div class="stat-card"><div class="val">${{CASES.length}}</div><div class="lbl">Test cases</div></div>
    <div class="stat-card"><div class="val ${{failing > 0 ? 'red' : 'green'}}">${{failing}}</div><div class="lbl">Failing tests</div></div>
    <div class="stat-card"><div class="val">${{avgMs}}ms</div><div class="lbl">Avg latency</div></div>
    <div class="stat-card"><div class="val">${{maxV || '—'}}</div><div class="lbl">Latest version</div></div>
  `;
}}

function buildCharts() {{
  // Trend chart: score per version (avg across all tests)
  const trendData = versions.map(v => {{
    const scores = CASES.map(c => {{
      const run = c.runs.filter(r => r.version === v);
      return run.length ? run[run.length-1].score : null;
    }}).filter(s => s !== null);
    return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  }});

  new Chart(document.getElementById('trend-chart'), {{
    type: 'line',
    data: {{
      labels: versions,
      datasets: [{{ label: 'Avg score', data: trendData.map(v => v ? Math.round(v*100) : null),
        borderColor: '#4f8ef7', tension: 0.4, fill: false, spanGaps: true }}]
    }},
    options: {{ plugins: {{ title: {{ display: true, text: 'Score trend by version', color: '#e2e8f0' }}, legend: {{ labels: {{ color: '#8892a4' }} }} }},
      scales: {{ y: {{ min: 0, max: 100, ticks: {{ color: '#8892a4', callback: v => v + '%' }}, grid: {{ color: '#2e3147' }} }}, x: {{ ticks: {{ color: '#8892a4' }}, grid: {{ color: '#2e3147' }} }} }},
      backgroundColor: '#1a1d27'
    }}
  }});

  // Latency chart: avg latency per model
  const modelLatency = models.map(m => {{
    const runs = CASES.flatMap(c => c.runs.filter(r => r.model === m));
    return runs.length ? Math.round(runs.reduce((s, r) => s + r.latency_ms, 0) / runs.length) : 0;
  }});

  new Chart(document.getElementById('latency-chart'), {{
    type: 'bar',
    data: {{
      labels: models,
      datasets: [{{ label: 'Avg latency (ms)', data: modelLatency,
        backgroundColor: '#4f8ef7aa' }}]
    }},
    options: {{ plugins: {{ title: {{ display: true, text: 'Avg latency by model', color: '#e2e8f0' }}, legend: {{ display: false }} }},
      scales: {{ y: {{ ticks: {{ color: '#8892a4', callback: v => v + 'ms' }}, grid: {{ color: '#2e3147' }} }}, x: {{ ticks: {{ color: '#8892a4' }}, grid: {{ color: '#2e3147' }} }} }}
    }}
  }});
}}

// Populate dropdowns
const modelSel = document.getElementById('model-select');
models.forEach(m => {{ const o = document.createElement('option'); o.value = m; o.textContent = m; modelSel.appendChild(o); }});
const verSel = document.getElementById('version-select');
versions.forEach(v => {{ const o = document.createElement('option'); o.value = v; o.textContent = v; verSel.appendChild(o); }});

buildSummary();
buildCharts();
renderTable();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Kyber prompt regression runner")
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help="Path to cases directory")
    parser.add_argument("--case-id", help="Run only a specific test case by ID")
    parser.add_argument(
        "--model",
        default="offline",
        help=(
            "Model to use: 'offline' (assertions on stored baseline, default), "
            "'local:ollama/MODEL' (local Ollama), 'ha:ai_task' (live HA)"
        ),
    )
    parser.add_argument("--no-report", action="store_true", help="Skip HTML report generation")
    args = parser.parse_args()

    version = _kyber_version()
    model = args.model

    cases = load_test_cases(args.cases)
    if not cases:
        print(f"No test cases found in {args.cases}")
        return 0

    if args.case_id:
        cases = [c for c in cases if c.get("id") == args.case_id]
        if not cases:
            print(f"No test case with id={args.case_id!r}")
            return 1

    print(f"\nLoaded {len(cases)} test case(s) from {args.cases}")

    all_results: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    for_report: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    for case in cases:
        case_dir: Path = case["_dir"]
        history = load_run_history(case_dir)

        if model == "offline":
            run_result = run_offline(case, version, "offline")
        elif model.startswith("local:ollama/"):
            ollama_model = model.split("local:ollama/", 1)[1]
            run_result = run_with_ollama(case, ollama_model, version, model)
        else:
            # ha:ai_task or unknown — fall back to offline for now
            print(f"  ⚠  Model '{model}' not yet supported in standalone runner; using offline mode")
            run_result = run_offline(case, version, model)

        # Append to history (keep last 50 runs)
        history.append(run_result)
        history = history[-50:]
        save_run_history(case_dir, history)

        all_results.append((case, run_result, history))
        for_report.append((case, history))

    print_score_table(all_results, version, model)

    if not args.no_report:
        html = _generate_html_report(for_report)
        REPORT_PATH.write_text(html, encoding="utf-8")
        print(f"HTML report: {REPORT_PATH}")

    # Exit code: 1 if any test failed
    any_failed = any(r["failed"] > 0 for _, r, _ in all_results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
