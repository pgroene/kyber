#!/usr/bin/env python3
"""Narrator performance + quality benchmark.

Runs the narrator's batch prompt against multiple Ollama models at different
batch sizes, measuring latency, token throughput, and output quality.

Usage:
    python scripts/narrator_bench.py
    python scripts/narrator_bench.py --models qwen3:4b-instruct qwen2.5:1.5b llama3.2:1b
    python scripts/narrator_bench.py --ollama http://192.168.1.10:11434
    python scripts/narrator_bench.py --batch-sizes 1 5 10 20 --runs 2
    python scripts/narrator_bench.py --report results.html
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ── Load narrator helpers without importing HA ────────────────────────────────
import sys, types, re as _re

def _load_narrator():
    """Load build_batch_prompt / parse_batch_response_v3 / build_entity_context without HA."""
    src_path = ROOT / "custom_components/kyber/entity_narrator.py"
    src = src_path.read_text(encoding="utf-8")

    # Stub out all HA and relative imports
    _stub_ha_modules()

    # Replace relative imports with stubs in source
    src = _re.sub(r"^from \.__future__.*$", "", src, flags=_re.MULTILINE)
    src = _re.sub(r"^from homeassistant.*$", "", src, flags=_re.MULTILINE)
    src = _re.sub(r"^from \.integration_explorer.*$",
                  "EXPLORER_PROGRESS_KEY = 'kyber_explorer_progress'", src, flags=_re.MULTILINE)
    src = _re.sub(r"^from \.language_hints.*$", "", src, flags=_re.MULTILINE)
    src = _re.sub(r"^from \..*$", "", src, flags=_re.MULTILINE)
    src = _re.sub(r"^import homeassistant.*$", "", src, flags=_re.MULTILINE)
    # Replace TYPE_CHECKING block
    src = src.replace("if TYPE_CHECKING:", "if False:")

    ns: dict[str, Any] = {
        "__name__": "entity_narrator",
        "__file__": str(src_path),
        "TYPE_CHECKING": False,
    }
    exec(compile(src, str(src_path), "exec"), ns)  # noqa: S102
    return ns["build_batch_prompt"], ns["parse_batch_response_v3"], ns["build_entity_context"]


def _stub_ha_modules():
    for mod in [
        "homeassistant", "homeassistant.core", "homeassistant.helpers",
        "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry",
        "homeassistant.components", "homeassistant.components.ai_task",
    ]:
        sys.modules.setdefault(mod, types.ModuleType(mod))

try:
    build_batch_prompt, parse_batch_response_v3, build_entity_context = _load_narrator()
except Exception as e:
    print(f"❌ Could not load narrator helpers: {e}")
    sys.exit(1)

# ── Realistic synthetic entities ─────────────────────────────────────────────
_SYNTHETIC_ENTITIES = [
    dict(entity_id="light.0x00178801041687_1a", name="Werkamer plafondlamp", domain="light",
         device_class=None, unit=None, area_name="Werkamer",
         state_str="on", attributes={"brightness": 200, "color_mode": "xy"},
         manufacturer="Signify", model="LCT016", siblings=[
             ("light.0x00178801041687_1b", "Werkamer spots"),
             ("light.0x00178801041687_1c", "Werkamer bureau"),
         ], dashboard_label="Plafondlamp werkamer"),
    dict(entity_id="binary_sensor.0x001788010b4f1234_occupancy", name="Beweging hal",
         domain="binary_sensor", device_class="motion", unit=None, area_name="Hal",
         state_str="off", attributes={},
         manufacturer="IKEA", model="E1745", siblings=[
             ("binary_sensor.0x001788010b4f1234_battery", "Beweging hal batterij"),
         ], dashboard_label=None),
    dict(entity_id="switch.onoff_keuken_espresso_304", name="Espressomachine keuken",
         domain="switch", device_class="outlet", unit=None, area_name="Keuken",
         state_str="off", attributes={},
         manufacturer="Shelly", model="Shelly Plus 1", siblings=[
             ("sensor.onoff_keuken_espresso_304_power", "Espressomachine vermogen"),
             ("sensor.onoff_keuken_espresso_304_energy", "Espressomachine energie"),
         ], dashboard_label="Espresso"),
    dict(entity_id="sensor.p1_electricity_instantaneous_usage", name="Huidig stroomverbruik",
         domain="sensor", device_class="power", unit="W", area_name=None,
         state_str="412", attributes={"state_class": "measurement"},
         manufacturer="DSMR", model=None, siblings=[
             ("sensor.p1_electricity_daily_usage", "Dagverbruik"),
             ("sensor.p1_gas_daily_usage", "Gasverbruik vandaag"),
         ], dashboard_label="Stroom nu"),
    dict(entity_id="climate.tado_woonkamer", name="Thermostaat woonkamer",
         domain="climate", device_class=None, unit=None, area_name="Woonkamer",
         state_str="heat", attributes={"current_temperature": 20.5, "target_temperature": 21.0,
                                        "hvac_modes": ["off", "heat", "auto"]},
         manufacturer="Tado", model="Tado Smart Thermostat V3+", siblings=[
             ("sensor.tado_woonkamer_temperature", "Temperatuur woonkamer"),
             ("sensor.tado_woonkamer_humidity", "Luchtvochtigheid woonkamer"),
         ], dashboard_label="Verwarming"),
    dict(entity_id="media_player.lg_oled_woonkamer", name="LG OLED TV",
         domain="media_player", device_class="tv", unit=None, area_name="Woonkamer",
         state_str="idle", attributes={"source_list": ["Netflix", "HDMI 1", "HDMI 2"]},
         manufacturer="LG", model="OLED65C1", siblings=[], dashboard_label="TV"),
    dict(entity_id="cover.rolluik_slaapkamer", name="Rolluik slaapkamer",
         domain="cover", device_class="shutter", unit=None, area_name="Slaapkamer",
         state_str="closed", attributes={"current_position": 0},
         manufacturer="Somfy", model="Somfy TaHoma", siblings=[
             ("cover.rolluik_slaapkamer_2", "Rolluik slaapkamer 2"),
         ], dashboard_label="Rolluik"),
    dict(entity_id="sensor.0x00124b00231ba109_temperature", name="Temperatuur buiten",
         domain="sensor", device_class="temperature", unit="°C", area_name="Buiten",
         state_str="13.4", attributes={"state_class": "measurement"},
         manufacturer="Sonoff", model="SNZB-02", siblings=[
             ("sensor.0x00124b00231ba109_humidity", "Luchtvochtigheid buiten"),
             ("sensor.0x00124b00231ba109_battery", "Batterij buiten sensor"),
         ], dashboard_label=None),
    dict(entity_id="lock.nuki_voordeur_deadbolt", name="Nuki voordeur",
         domain="lock", device_class="lock", unit=None, area_name="Entree",
         state_str="locked", attributes={},
         manufacturer="Nuki", model="Nuki Smart Lock 3.0 Pro", siblings=[
             ("sensor.nuki_voordeur_battery_critical", "Nuki batterij"),
         ], dashboard_label="Voordeur"),
    dict(entity_id="vacuum.roomba_j7_woonkamer", name="Roomba stofzuiger",
         domain="vacuum", device_class=None, unit=None, area_name="Woonkamer",
         state_str="docked", attributes={"status": "Charging", "battery_level": 98},
         manufacturer="iRobot", model="Roomba j7+", siblings=[], dashboard_label="Roomba"),
    dict(entity_id="sensor.electricity_meter_power_phase_l1", name="Fase L1 vermogen",
         domain="sensor", device_class="power", unit="W", area_name=None,
         state_str="134", attributes={"state_class": "measurement"},
         manufacturer="DSMR", model=None, siblings=[
             ("sensor.electricity_meter_power_phase_l2", "Fase L2 vermogen"),
             ("sensor.electricity_meter_power_phase_l3", "Fase L3 vermogen"),
         ], dashboard_label=None),
    dict(entity_id="binary_sensor.deurbel_voordeur_ding", name="Deurbel",
         domain="binary_sensor", device_class="sound", unit=None, area_name="Entree",
         state_str="off", attributes={},
         manufacturer="Ring", model="Ring Video Doorbell 4", siblings=[], dashboard_label="Deurbel"),
    dict(entity_id="sensor.solaredge_current_power", name="Zonnepanelen vermogen",
         domain="sensor", device_class="power", unit="W", area_name=None,
         state_str="2840", attributes={"state_class": "measurement"},
         manufacturer="SolarEdge", model="SE5000H", siblings=[
             ("sensor.solaredge_lifetime_energy", "Totale zonne-energie"),
             ("sensor.solaredge_today_energy", "Zonne-energie vandaag"),
         ], dashboard_label="Zonnepanelen"),
    dict(entity_id="light.hue_go_terras", name="Hue Go terras",
         domain="light", device_class=None, unit=None, area_name="Terras",
         state_str="off", attributes={"effect_list": ["colorloop", "none"]},
         manufacturer="Signify", model="Hue Go", siblings=[], dashboard_label=None),
    dict(entity_id="sensor.p1_gas_meter_m3", name="Gasmeter stand",
         domain="sensor", device_class="gas", unit="m³", area_name=None,
         state_str="8432.156", attributes={"state_class": "total_increasing"},
         manufacturer="DSMR", model=None, siblings=[], dashboard_label="Gas"),
    dict(entity_id="binary_sensor.window_sensor_keuken_contact", name="Raam keuken",
         domain="binary_sensor", device_class="window", unit=None, area_name="Keuken",
         state_str="off", attributes={},
         manufacturer="Aqara", model="MCCGQ11LM", siblings=[], dashboard_label=None),
    dict(entity_id="fan.itho_ventilatie_woonkamer", name="Ventilatie woonkamer",
         domain="fan", device_class=None, unit=None, area_name="Woonkamer",
         state_str="on", attributes={"percentage": 50, "preset_mode": "normal"},
         manufacturer="Itho Daalderop", model="HRU ECO4", siblings=[], dashboard_label="Ventilatie"),
    dict(entity_id="sensor.airvisual_air_quality_index", name="Luchtkwaliteitsindex",
         domain="sensor", device_class="aqi", unit="AQI", area_name=None,
         state_str="23", attributes={},
         manufacturer="IQAir", model="AirVisual Pro", siblings=[], dashboard_label=None),
    dict(entity_id="switch.0x001788010c45abcd_switch", name="Zwembadpomp tuin",
         domain="switch", device_class="outlet", unit=None, area_name="Tuin",
         state_str="on", attributes={},
         manufacturer="Sonoff", model="ZBMINI", siblings=[], dashboard_label="Zwembadpomp"),
    dict(entity_id="sensor.growatt_daily_energy", name="Omvormer dagopbrengst",
         domain="sensor", device_class="energy", unit="kWh", area_name=None,
         state_str="12.4", attributes={"state_class": "total_increasing"},
         manufacturer="Growatt", model="SPF 5000ES", siblings=[
             ("sensor.growatt_total_energy", "Omvormer totaal"),
         ], dashboard_label=None),
]

# Build entity contexts once
_ENTITY_CONTEXTS = []
for e in _SYNTHETIC_ENTITIES:
    ctx = build_entity_context(
        entity_id=e["entity_id"], name=e["name"], domain=e["domain"],
        device_class=e["device_class"], unit=e["unit"], area_name=e["area_name"],
        state_str=e["state_str"], attributes=e["attributes"],
        manufacturer=e["manufacturer"], model=e["model"],
        siblings=e["siblings"], dashboard_label=e["dashboard_label"],
    )
    _ENTITY_CONTEXTS.append((e["entity_id"], ctx))


# ── Ollama call ────────────────────────────────────────────────────────────────
def _ollama_call(model: str, prompt: str, url: str, timeout: int = 180) -> tuple[str, int, int, float]:
    """Returns (response_text, prompt_tokens, completion_tokens, elapsed_sec)."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2048},
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama unreachable at {url}: {e}") from e
    elapsed = time.perf_counter() - t0
    return (
        d.get("response", ""),
        d.get("prompt_eval_count", 0) or 0,
        d.get("eval_count", 0) or 0,
        elapsed,
    )


# ── Quality scoring ────────────────────────────────────────────────────────────
@dataclass
class BatchResult:
    model: str
    batch_size: int
    run: int
    elapsed_sec: float
    prompt_tokens: int
    completion_tokens: int
    entities_requested: int
    entities_parsed: int       # JSON objects we could parse
    entities_with_eid: int     # descriptions containing entity_id verbatim
    entities_with_terms: int   # entries with ≥2 search_terms
    entities_with_type: int    # entries with non-empty device_type
    raw_response: str = field(repr=False, default="")

    @property
    def parse_rate(self) -> float:
        return self.entities_parsed / max(self.entities_requested, 1)

    @property
    def eid_rate(self) -> float:
        return self.entities_with_eid / max(self.entities_requested, 1)

    @property
    def quality_score(self) -> float:
        """0-100: weighted blend of parse, eid presence, search_terms, device_type."""
        p = self.parse_rate * 40
        e = self.eid_rate * 30
        t = (self.entities_with_terms / max(self.entities_requested, 1)) * 20
        d = (self.entities_with_type / max(self.entities_requested, 1)) * 10
        return p + e + t + d

    @property
    def tok_per_sec(self) -> float:
        return self.completion_tokens / max(self.elapsed_sec, 0.001)

    @property
    def ms_per_entity(self) -> float:
        return (self.elapsed_sec * 1000) / max(self.entities_requested, 1)


def _score_response(raw: str, entity_ids: list[str]) -> tuple[int, int, int, int]:
    """Returns (entities_parsed, entities_with_eid, entities_with_terms, entities_with_type)."""
    parsed = parse_batch_response_v3(raw, entity_ids)
    with_eid = sum(1 for eid, info in parsed.items() if eid in info.get("description", ""))
    with_terms = sum(1 for info in parsed.values() if len(info.get("search_terms", [])) >= 2)
    with_type = sum(1 for info in parsed.values() if info.get("device_type", ""))
    return len(parsed), with_eid, with_terms, with_type


# ── List available Ollama models ───────────────────────────────────────────────
def _list_models(url: str) -> list[str]:
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        return [m["name"] for m in d.get("models", [])]
    except Exception:
        return []


# ── Benchmark runner ───────────────────────────────────────────────────────────
def run_benchmark(
    models: list[str],
    batch_sizes: list[int],
    ollama_url: str,
    runs: int = 2,
    verbose: bool = False,
) -> list[BatchResult]:
    results: list[BatchResult] = []
    total = len(models) * len(batch_sizes) * runs
    done = 0

    for model in models:
        print(f"\n{'─'*60}")
        print(f"  Model: {model}")
        print(f"{'─'*60}")
        for bs in batch_sizes:
            pairs = _ENTITY_CONTEXTS[:bs]
            if len(pairs) < bs:
                print(f"  ⚠  Only {len(pairs)} synthetic entities, skipping batch_size={bs}")
                continue
            prompt = build_batch_prompt(pairs, home_lang="nl", devices_hint="")
            entity_ids = [p[0] for p in pairs]
            prompt_chars = len(prompt)

            for run_i in range(1, runs + 1):
                done += 1
                print(f"  [{done}/{total}] batch={bs:2d}  run={run_i}/{runs}  "
                      f"prompt={prompt_chars:,} chars  ", end="", flush=True)
                try:
                    raw, pt, ct, elapsed = _ollama_call(model, prompt, ollama_url)
                    parsed, with_eid, with_terms, with_type = _score_response(raw, entity_ids)
                    r = BatchResult(
                        model=model, batch_size=bs, run=run_i,
                        elapsed_sec=elapsed, prompt_tokens=pt, completion_tokens=ct,
                        entities_requested=bs, entities_parsed=parsed,
                        entities_with_eid=with_eid, entities_with_terms=with_terms,
                        entities_with_type=with_type, raw_response=raw,
                    )
                    print(f"✅  {elapsed:.1f}s  {r.tok_per_sec:.0f} tok/s  "
                          f"parsed={parsed}/{bs}  quality={r.quality_score:.0f}/100")
                    if verbose:
                        print(f"      raw snippet: {raw[:200]!r}")
                    results.append(r)
                except Exception as e:
                    print(f"❌  {e}")
                    done_pct = done / total
    return results


# ── Report generation ──────────────────────────────────────────────────────────
def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def print_summary_table(results: list[BatchResult]) -> None:
    # Group by (model, batch_size) → average
    from collections import defaultdict
    groups: dict[tuple[str, int], list[BatchResult]] = defaultdict(list)
    for r in results:
        groups[(r.model, r.batch_size)].append(r)

    models = sorted({r.model for r in results})
    batch_sizes = sorted({r.batch_size for r in results})

    print("\n" + "═"*90)
    print("  RESULTS SUMMARY")
    print("═"*90)

    # Speed table
    print("\n📊 SPEED (avg over runs)")
    print(f"  {'Model':<30} {'Batch':>5}  {'Elapsed':>8}  {'ms/entity':>10}  {'tok/s':>7}  {'tok total':>10}")
    print(f"  {'-'*30} {'-'*5}  {'-'*8}  {'-'*10}  {'-'*7}  {'-'*10}")
    for model in models:
        for bs in batch_sizes:
            rs = groups.get((model, bs), [])
            if not rs:
                continue
            avg_elapsed = _avg([r.elapsed_sec for r in rs])
            avg_mpe = _avg([r.ms_per_entity for r in rs])
            avg_tps = _avg([r.tok_per_sec for r in rs])
            avg_tot = _avg([r.prompt_tokens + r.completion_tokens for r in rs])
            # Short model name for display
            mshort = model[:30]
            print(f"  {mshort:<30} {bs:>5}  {avg_elapsed:>7.1f}s  {avg_mpe:>9.0f}ms  "
                  f"{avg_tps:>6.0f}  {avg_tot:>10.0f}")

    # Quality table
    print("\n🎯 QUALITY (avg over runs)")
    print(f"  {'Model':<30} {'Batch':>5}  {'Score':>6}  {'Parsed':>8}  "
          f"{'Has eid':>8}  {'Terms≥2':>8}  {'DevType':>8}")
    print(f"  {'-'*30} {'-'*5}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
    for model in models:
        for bs in batch_sizes:
            rs = groups.get((model, bs), [])
            if not rs:
                continue
            avg_q = _avg([r.quality_score for r in rs])
            avg_pr = _avg([r.parse_rate * 100 for r in rs])
            avg_er = _avg([r.eid_rate * 100 for r in rs])
            avg_tr = _avg([r.entities_with_terms / max(r.entities_requested, 1) * 100 for r in rs])
            avg_dr = _avg([r.entities_with_type / max(r.entities_requested, 1) * 100 for r in rs])
            mshort = model[:30]
            print(f"  {mshort:<30} {bs:>5}  {avg_q:>5.0f}%  {avg_pr:>7.0f}%  "
                  f"{avg_er:>7.0f}%  {avg_tr:>7.0f}%  {avg_dr:>7.0f}%")

    # Best model per batch size
    print("\n🏆 BEST SPEED-QUALITY TRADEOFF (quality_score / elapsed_sec)")
    print(f"  {'Batch':>5}  {'Best model':<30}  {'Score':>6}  {'Elapsed':>8}")
    print(f"  {'-'*5}  {'-'*30}  {'-'*6}  {'-'*8}")
    for bs in batch_sizes:
        candidates = []
        for model in models:
            rs = groups.get((model, bs), [])
            if rs:
                score = _avg([r.quality_score for r in rs])
                elapsed = _avg([r.elapsed_sec for r in rs])
                candidates.append((model, score, elapsed))
        if candidates:
            # Sort by quality desc, then speed
            best = sorted(candidates, key=lambda x: (-x[1], x[2]))[0]
            print(f"  {bs:>5}  {best[0][:30]:<30}  {best[1]:>5.0f}%  {best[2]:>7.1f}s")
    print()


def save_html_report(results: list[BatchResult], path: Path) -> None:
    from collections import defaultdict
    groups: dict[tuple[str, int], list[BatchResult]] = defaultdict(list)
    for r in results:
        groups[(r.model, r.batch_size)].append(r)

    models = sorted({r.model for r in results})
    batch_sizes = sorted({r.batch_size for r in results})

    rows_speed = []
    rows_quality = []
    for model in models:
        for bs in batch_sizes:
            rs = groups.get((model, bs), [])
            if not rs:
                continue
            avg_q = _avg([r.quality_score for r in rs])
            avg_elapsed = _avg([r.elapsed_sec for r in rs])
            avg_mpe = _avg([r.ms_per_entity for r in rs])
            avg_tps = _avg([r.tok_per_sec for r in rs])
            avg_pr = _avg([r.parse_rate * 100 for r in rs])
            avg_er = _avg([r.eid_rate * 100 for r in rs])
            avg_tr = _avg([r.entities_with_terms / max(r.entities_requested, 1) * 100 for r in rs])
            avg_dr = _avg([r.entities_with_type / max(r.entities_requested, 1) * 100 for r in rs])
            q_color = "#4caf50" if avg_q >= 80 else "#ff9800" if avg_q >= 60 else "#f44336"
            rows_speed.append(
                f"<tr><td>{model}</td><td>{bs}</td>"
                f"<td>{avg_elapsed:.1f}s</td><td>{avg_mpe:.0f}ms</td><td>{avg_tps:.0f}</td></tr>"
            )
            rows_quality.append(
                f'<tr><td>{model}</td><td>{bs}</td>'
                f'<td style="color:{q_color};font-weight:bold">{avg_q:.0f}%</td>'
                f'<td>{avg_pr:.0f}%</td><td>{avg_er:.0f}%</td>'
                f'<td>{avg_tr:.0f}%</td><td>{avg_dr:.0f}%</td></tr>'
            )

    # Build chart data for speed vs quality scatter
    scatter_points = []
    for model in models:
        for bs in batch_sizes:
            rs = groups.get((model, bs), [])
            if rs:
                scatter_points.append({
                    "model": model, "batch": bs,
                    "quality": round(_avg([r.quality_score for r in rs]), 1),
                    "elapsed": round(_avg([r.elapsed_sec for r in rs]), 2),
                    "tps": round(_avg([r.tok_per_sec for r in rs]), 1),
                })

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Kyber Narrator Benchmark</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #222; }}
  h1 {{ border-bottom: 2px solid #03a9f4; padding-bottom: .5em; }}
  h2 {{ color: #03a9f4; margin-top: 2em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th {{ background: #03a9f4; color: #fff; padding: 8px 12px; text-align: left; }}
  td {{ padding: 7px 12px; border-bottom: 1px solid #eee; }}
  tr:nth-child(even) td {{ background: #f9f9f9; }}
  .chip {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: .85em; }}
  canvas {{ max-width: 100%; margin: 1em 0; }}
  .legend {{ display: flex; gap: 1em; flex-wrap: wrap; margin: .5em 0; font-size: .85em; }}
  .legend span {{ display: flex; align-items: center; gap: 4px; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
</style>
</head>
<body>
<h1>🚀 Kyber Narrator Benchmark</h1>
<p>Models tested: {", ".join(f"<code>{m}</code>" for m in models)} &nbsp;|&nbsp;
   Batch sizes: {", ".join(str(b) for b in batch_sizes)} &nbsp;|&nbsp;
   Entities: 20 synthetic Dutch home entities</p>

<h2>⚡ Speed</h2>
<table>
<thead><tr><th>Model</th><th>Batch size</th><th>Elapsed</th><th>ms / entity</th><th>tok/s</th></tr></thead>
<tbody>{"".join(rows_speed)}</tbody>
</table>

<h2>🎯 Quality</h2>
<p>Score = 40% parse rate + 30% entity_id in description + 20% ≥2 search terms + 10% device_type present</p>
<table>
<thead><tr><th>Model</th><th>Batch size</th><th>Quality score</th><th>Parsed</th><th>Has entity_id</th><th>Terms ≥2</th><th>Device type</th></tr></thead>
<tbody>{"".join(rows_quality)}</tbody>
</table>

<h2>📈 Speed vs Quality</h2>
<canvas id="chart" width="900" height="400"></canvas>
<div class="legend" id="legend"></div>

<script>
const data = {json.dumps(scatter_points)};
const models = [...new Set(data.map(d => d.model))];
const palette = ["#03a9f4","#ff9800","#4caf50","#e91e63","#9c27b0","#00bcd4","#ff5722"];
const colors = Object.fromEntries(models.map((m,i)=>[m, palette[i%palette.length]]));

const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");
const W = canvas.width, H = canvas.height;
const pad = {{l:60, r:20, t:20, b:50}};

// Axes
const maxElapsed = Math.max(...data.map(d=>d.elapsed)) * 1.1 || 10;
const minQ = 0, maxQ = 100;

function toX(elapsed) {{ return pad.l + (elapsed / maxElapsed) * (W - pad.l - pad.r); }}
function toY(quality) {{ return H - pad.b - ((quality - minQ) / (maxQ - minQ)) * (H - pad.t - pad.b); }}

// Grid
ctx.strokeStyle = "#eee"; ctx.lineWidth = 1;
for (let q = 0; q <= 100; q += 20) {{
    ctx.beginPath(); ctx.moveTo(pad.l, toY(q)); ctx.lineTo(W-pad.r, toY(q)); ctx.stroke();
    ctx.fillStyle="#999"; ctx.font="11px sans-serif"; ctx.textAlign="right";
    ctx.fillText(q+"%", pad.l-4, toY(q)+4);
}}
for (let t = 0; t <= maxElapsed; t += Math.ceil(maxElapsed/5)) {{
    const x = toX(t);
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, H-pad.b); ctx.stroke();
    ctx.fillStyle="#999"; ctx.textAlign="center";
    ctx.fillText(t+"s", x, H-pad.b+16);
}}

// Axis labels
ctx.fillStyle="#333"; ctx.font="13px sans-serif";
ctx.textAlign="center"; ctx.fillText("Elapsed time (s)", W/2, H-2);
ctx.save(); ctx.translate(14, H/2); ctx.rotate(-Math.PI/2);
ctx.fillText("Quality score", 0, 0); ctx.restore();

// Points
data.forEach(d => {{
    const x = toX(d.elapsed), y = toY(d.quality);
    const r = 6 + d.batch * 0.5;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 2*Math.PI);
    ctx.fillStyle = colors[d.model] + "bb";
    ctx.strokeStyle = colors[d.model];
    ctx.lineWidth = 2; ctx.fill(); ctx.stroke();
    ctx.fillStyle="#333"; ctx.font="10px sans-serif"; ctx.textAlign="center";
    ctx.fillText("b"+d.batch, x, y+3);
}});

// Legend
const leg = document.getElementById("legend");
models.forEach(m => {{
    const span = document.createElement("span");
    span.innerHTML = `<span class="dot" style="background:${{colors[m]}}"></span> ${{m}}`;
    leg.appendChild(span);
}});
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    print(f"  📄 HTML report saved → {path}")


def save_json_results(results: list[BatchResult], path: Path) -> None:
    data = [
        {k: v for k, v in r.__dict__.items() if k != "raw_response"}
        for r in results
    ]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  💾 JSON results saved → {path}")


# ── Main ───────────────────────────────────────────────────────────────────────
DEFAULT_MODELS = [
    "qwen3:4b-instruct",
    "qwen2.5:1.5b",
    "llama3.2:1b",
]
DEFAULT_BATCH_SIZES = [1, 5, 10, 20]

def main() -> None:
    ap = argparse.ArgumentParser(description="Kyber narrator model benchmark")
    ap.add_argument("--models", nargs="+", default=None,
                    help="Ollama model names to test (default: auto-detect or built-in defaults)")
    ap.add_argument("--batch-sizes", nargs="+", type=int, default=DEFAULT_BATCH_SIZES,
                    help="Batch sizes to test (default: 1 5 10 20)")
    ap.add_argument("--ollama", default="http://localhost:11434",
                    help="Ollama base URL (default: http://localhost:11434)")
    ap.add_argument("--runs", type=int, default=2,
                    help="Number of runs per (model, batch_size) (default: 2)")
    ap.add_argument("--report", default=None,
                    help="Save HTML report to this path (default: tests/narrator_bench/report.html)")
    ap.add_argument("--json", default=None,
                    help="Save raw JSON results to this path")
    ap.add_argument("--list-models", action="store_true",
                    help="List available Ollama models and exit")
    ap.add_argument("--verbose", action="store_true",
                    help="Print raw response snippets")
    args = ap.parse_args()

    if args.list_models:
        print(f"Available models at {args.ollama}:")
        for m in _list_models(args.ollama):
            print(f"  {m}")
        return

    # Resolve models
    models = args.models
    if not models:
        available = _list_models(args.ollama)
        if available:
            # Filter to models we know work well, plus anything small
            prefer = [m for m in DEFAULT_MODELS if any(m.split(":")[0] in a for a in available)]
            # Add any ≤3b models not already in prefer
            small = [a for a in available if any(
                s in a.lower() for s in ["0.5b","1b","1.5b","2b","3b","mini","tiny","small"]
            ) and a not in prefer]
            models = (prefer + small[:2]) or available[:3]
            print(f"Auto-selected models: {models}")
        else:
            models = DEFAULT_MODELS
            print(f"Could not reach Ollama, using defaults: {models}")

    print(f"\nKyber Narrator Benchmark")
    print(f"  Ollama:      {args.ollama}")
    print(f"  Models:      {models}")
    print(f"  Batch sizes: {args.batch_sizes}")
    print(f"  Runs/cell:   {args.runs}")
    print(f"  Entities:    {len(_ENTITY_CONTEXTS)} synthetic Dutch home entities")

    # Verify connectivity using the tags endpoint (fast, no model load)
    try:
        available_check = _list_models(args.ollama)
        if not available_check:
            raise RuntimeError("No models returned")
        print(f"  ✅ Ollama reachable — {len(available_check)} model(s) available")
    except Exception as e:
        print(f"\n❌ Cannot reach Ollama at {args.ollama}: {e}")
        print("   Start Ollama and ensure at least one model is pulled.")
        sys.exit(1)

    results = run_benchmark(
        models=models,
        batch_sizes=args.batch_sizes,
        ollama_url=args.ollama,
        runs=args.runs,
        verbose=args.verbose,
    )

    if not results:
        print("No results collected.")
        return

    print_summary_table(results)

    out_dir = ROOT / "tests" / "narrator_bench"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = Path(args.report) if args.report else out_dir / "report.html"
    save_html_report(results, report_path)

    json_path = Path(args.json) if args.json else out_dir / "results.json"
    save_json_results(results, json_path)


if __name__ == "__main__":
    main()
