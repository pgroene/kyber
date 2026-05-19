"""Plot eval score improvement over time."""
import json
import os
import glob
import sys

files = sorted(glob.glob("scripts/eval_results/*.json"))

# Build table of (label, avg_score_per_run[])
sessions = []
for f in files:
    data = json.load(open(f, encoding="utf-8"))
    runs = data.get("runs", [])
    if not runs:
        continue
    name = os.path.basename(f).replace("eval_", "").replace(".json", "")
    for i, r in enumerate(runs):
        sessions.append({
            "file": os.path.basename(f),
            "run_idx": i,
            "avg": r.get("avg", r.get("avg_score", 0)),
            "passes": r.get("passes", 0),
            "total": r.get("total", 10),
        })

if not sessions:
    print("No data found")
    sys.exit(1)

# Print table
print("\nRaw runs in order:")
print(f"{'#':>4}  {'File':<55} {'Run':>3}  {'Avg':>5}  {'Pass':>6}")
print("-" * 80)
for i, s in enumerate(sessions):
    print(f"{i+1:>4}  {s['file']:<55} {s['run_idx']+1:>3}  {s['avg']:>5.1f}  {s['passes']}/{s['total']}")

# Try to plot with matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    x = list(range(1, len(sessions) + 1))
    avgs = [s["avg"] for s in sessions]
    passes = [s["passes"] for s in sessions]
    totals = [s["total"] for s in sessions]
    pass_pct = [p / t * 100 for p, t in zip(passes, totals)]

    # Color by file to group session runs
    file_names = list(dict.fromkeys(s["file"] for s in sessions))
    colors = plt.cm.tab10(np.linspace(0, 1, len(file_names)))
    file_color = {f: colors[i] for i, f in enumerate(file_names)}
    bar_colors = [file_color[s["file"]] for s in sessions]

    # Labels: short session number
    labels = []
    seen = {}
    for s in sessions:
        n = seen.get(s["file"], 0) + 1
        seen[s["file"]] = n
        labels.append(f"S{file_names.index(s['file'])+1}R{n}")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    fig.suptitle("Kyber Prompt Eval — Score Improvement Over Time\n(qwen3:4b-instruct)", fontsize=14, fontweight="bold")

    # Top: avg score (0-10)
    bars = ax1.bar(x, avgs, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax1.axhline(y=10, color="green", linestyle="--", alpha=0.4, label="Perfect (10.0)")
    ax1.axhline(y=7, color="orange", linestyle="--", alpha=0.4, label="Pass threshold (7.0)")
    ax1.set_ylabel("Avg Score (0–10)", fontweight="bold")
    ax1.set_ylim(0, 11)
    ax1.set_yticks(range(0, 11, 1))
    ax1.grid(axis="y", alpha=0.3)
    ax1.legend(loc="lower right", fontsize=9)
    for bar, val in zip(bars, avgs):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, f"{val:.1f}",
                 ha="center", va="bottom", fontsize=8, fontweight="bold")

    # Bottom: pass rate %
    bars2 = ax2.bar(x, pass_pct, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax2.axhline(y=100, color="green", linestyle="--", alpha=0.4)
    ax2.set_ylabel("Pass Rate (%)", fontweight="bold")
    ax2.set_ylim(0, 115)
    ax2.set_yticks(range(0, 110, 10))
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
    ax2.set_xlabel("Session (S=session, R=run within session)", fontweight="bold")
    ax2.grid(axis="y", alpha=0.3)
    for bar, val, ps, tt in zip(bars2, pass_pct, passes, totals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{ps}/{tt}",
                 ha="center", va="bottom", fontsize=8, fontweight="bold")

    # Legend for sessions
    patches = [mpatches.Patch(color=file_color[f], label=f"S{i+1}: {f.split('_')[1][:8]}") for i, f in enumerate(file_names)]
    fig.legend(handles=patches, loc="upper right", fontsize=8, title="Sessions", title_fontsize=9,
               bbox_to_anchor=(1.0, 0.95))

    plt.tight_layout()
    out = "scripts/eval_results/score_progress.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nPlot saved → {out}")

except ImportError:
    print("\nmatplotlib not available — install with: pip install matplotlib")
