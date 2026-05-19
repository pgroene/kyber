#!/usr/bin/env python3
"""
Kyber Prompt Evaluation & Auto-Improvement Harness.

Modes:
  Default   — N improvement iterations, score table + change log
  --compare — 3 runs WITH memory vs 3 runs WITHOUT memory, side-by-side table
              showing what relies on knowledge facts and what doesn't

"Memory" = knowledge facts pre-injected before the User: turn (simulating Kyber's
semantic-search injection) + search_knowledge tool returns relevant facts.
"No memory" = no pre-injected facts, search_knowledge always returns empty.

Usage:
    python scripts/prompt_eval.py --model qwen3:4b-instruct --compare
    python scripts/prompt_eval.py --model qwen3:4b-instruct --iterations 5 --no-judge
    python scripts/prompt_eval.py --model qwen3:4b-instruct --save-prompt

Expected runtime: ~2-3 min per iteration (Qwen3 4b, local GPU).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ─── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent


# ─── Load Kyber source (no HA dependencies) ───────────────────────────────────
def _load_system_prompt_template() -> str:
    src = (ROOT / "custom_components/kyber/const.py").read_text(encoding="utf-8")
    start = src.find('SYSTEM_PROMPT_TEMPLATE = """')
    if start == -1:
        raise RuntimeError("SYSTEM_PROMPT_TEMPLATE not found in const.py")
    open_end = src.find('"""', start) + 3
    # Handle """\<newline>  (line continuation)
    if open_end < len(src) and src[open_end] == "\\" and src[open_end + 1] == "\n":
        content_start = open_end + 2
    elif open_end < len(src) and src[open_end] == "\n":
        content_start = open_end + 1
    else:
        content_start = open_end
    close = src.find('\n"""', content_start)
    if close == -1:
        raise RuntimeError("No closing triple-quote for SYSTEM_PROMPT_TEMPLATE")
    return src[content_start : close + 1]  # include trailing newline


def _load_response_processing():
    src = (ROOT / "custom_components/kyber/response_processing.py").read_text(encoding="utf-8")
    src = re.sub(r"from __future__.*?\n", "", src, count=1)
    src = src.replace("from .const import TOOL_CALL_MAX_ROUNDS", "TOOL_CALL_MAX_ROUNDS = 5")
    ns: dict = {}
    exec(compile(src, "response_processing.py", "exec"), ns)  # noqa: S102
    return (
        ns["_parse_tool_calls"],
        ns["_extract_plan_block"],
        ns["_strip_tool_calls"],
        ns.get("_normalize_json_plan_blocks"),
        ns.get("_rewrap_bare_action_fences"),
    )


_parse_tool_calls, _extract_plan_block, _strip_tool_calls, _normalize_json_plan_blocks, _rewrap_bare_action_fences = (
    _load_response_processing()
)
_BASE_PROMPT = _load_system_prompt_template()

# ─── Memory mode flag ─────────────────────────────────────────────────────────
# Toggled at runtime by run_comparison(); all tool stubs read this.
_MEMORY_ENABLED: bool = True

# Facts that Kyber's semantic search would pre-inject for each scenario.
# Keys are substrings that match the user message (lower-cased).
_KNOWLEDGE_FACTS: dict[str, list[str]] = {
    "werkamer":     ["light.0x001788010416871a is the werkamer bureaulamp — use get_area_entities(area='werkamer', domain='light') to find it reliably"],
    "keuken":       ["switch.koffiezetapparaat is the coffee machine in keuken", "light.keuken_spots and light.keuken_aanrecht are the kitchen lights"],
    "woonkamer":    ["media_player.woonkamer_tv is the main TV in woonkamer", "climate.woonkamer controls the central heating"],
    "peter":        ["Peter is currently home — person.peter state is 'home'",
                     "binary_sensor.presence_werkkamer_304_presence = on means Peter is in the werkkamer (occupancy sensor)"],
    "lisa":         ["Lisa is not home — person.lisa state is 'not_home'"],
    "buiten":       ["sensor.outside_temp is the outdoor temperature sensor (currently reading 14.2 °C)"],
    "verwarming":   ["climate.woonkamer controls the heating. Use climate.set_temperature with temperature param."],
    "koffie":       ["switch.0xa4c138d5f4f912f2 (onoff_keuken_espresso_304) is the espresso machine power switch in keuken — use switch.turn_on to start it",
                     "switch.onoff_keuken_lamp_espresso_307 is the LAMP near the espresso machine, NOT the machine itself"],
    "espresso":     ["switch.0xa4c138d5f4f912f2 (onoff_keuken_espresso_304) is the espresso machine power switch — use switch.turn_on",
                     "input_text.ai_espresso_is_on is a STATUS display, cannot be controlled"],
    "televisie":    ["media_player.woonkamer_tv is the living-room TV — use media_player.turn_off"],
    "tv":           ["media_player.woonkamer_tv entity controls the living-room television"],
    "lichten":      ["Use get_area_entities(area=<area_id>, domain='light') to list lights in a room — never guess entity IDs"],
    "lampen":       ["Use get_area_entities(area=<area_id>, domain='light') to discover lights — never guess entity IDs"],
    "automatisering": ["To create automations use a plan block with type 'create_automation' and an 'automation' sub-object"],
    "waar":         ["Peter is currently home — person.peter state is 'home'",
                     "binary_sensor.presence_werkkamer_304_presence = on — Peter is in the werkkamer"],
}


# ─── Simulated Home ────────────────────────────────────────────────────────────
SIM_AREAS = [
    {"area_id": "badkamer",       "name": "Badkamer"},
    {"area_id": "gang",           "name": "Gang"},
    {"area_id": "keuken",         "name": "Keuken"},
    {"area_id": "slaapkamer_peter","name": "Slaapkamer Peter"},
    {"area_id": "werkamer",       "name": "Werkamer"},
    {"area_id": "werkkamer",      "name": "Werkkamer"},
    {"area_id": "woonkamer",      "name": "Woonkamer"},
]

SIM_ENTITIES: dict[str, dict] = {
    "light.woonkamer_lamp":         {"state": "on",  "attributes": {"friendly_name": "Woonkamer lamp", "brightness": 200}, "area_id": "woonkamer", "domain": "light"},
    "light.woonkamer_sfeer":        {"state": "off", "attributes": {"friendly_name": "Woonkamer sfeerlamp"},               "area_id": "woonkamer", "domain": "light"},
    "light.keuken_spots":           {"state": "off", "attributes": {"friendly_name": "Keuken spots"},                      "area_id": "keuken",    "domain": "light"},
    "light.keuken_aanrecht":        {"state": "off", "attributes": {"friendly_name": "Keuken aanrechtverlichting"},         "area_id": "keuken",    "domain": "light"},
    "light.0x001788010416871a":     {"state": "on",  "attributes": {"friendly_name": "Werkamer bureaulamp"},               "area_id": "werkamer",  "domain": "light"},
    "light.gang_lamp":              {"state": "off", "attributes": {"friendly_name": "Gang lamp"},                         "area_id": "gang",      "domain": "light"},
    "climate.woonkamer":            {"state": "heating", "attributes": {"friendly_name": "Woonkamer thermostaat", "current_temperature": 20.1, "temperature": 21.0, "hvac_modes": ["heat", "cool", "off", "auto"]}, "area_id": "woonkamer", "domain": "climate"},
    "sensor.outside_temp":          {"state": "14.2", "attributes": {"friendly_name": "Buitentemperatuur", "unit_of_measurement": "°C", "device_class": "temperature"}, "domain": "sensor"},
    "sensor.woonkamer_temp":        {"state": "20.1", "attributes": {"friendly_name": "Woonkamer temperatuur", "unit_of_measurement": "°C"}, "area_id": "woonkamer", "domain": "sensor"},
    "media_player.woonkamer_tv":    {"state": "playing", "attributes": {"friendly_name": "Woonkamer TV", "source": "Netflix"}, "area_id": "woonkamer", "domain": "media_player"},
    "switch.koffiezetapparaat":     {"state": "on",  "attributes": {"friendly_name": "Koffiezetapparaat"},                "area_id": "keuken",    "domain": "switch"},
    "switch.0xa4c138d5f4f912f2":        {"state": "off", "attributes": {"friendly_name": "onoff_keuken_espresso_304"}, "area_id": "keuken", "domain": "switch"},
    "switch.onoff_keuken_lamp_espresso_307": {"state": "off", "attributes": {"friendly_name": "onoff_keuken_lamp_espresso_307"}, "area_id": "keuken", "domain": "switch"},
    "input_text.ai_espresso_is_on":     {"state": "Off",  "attributes": {"friendly_name": "Espresso Machine On"}, "domain": "input_text"},
    "input_text.ai_espresso_preheating_is_on": {"state": "Off", "attributes": {"friendly_name": "Espresso Machine Preheating"}, "domain": "input_text"},
    "binary_sensor.presence_werkkamer_304_presence": {"state": "on", "attributes": {"friendly_name": "presence_werkkamer_304 Occupancy", "device_class": "occupancy"}, "area_id": "werkkamer", "domain": "binary_sensor"},
    "person.peter":                 {"state": "home",      "attributes": {"friendly_name": "Peter"}, "domain": "person"},
    "person.lisa":                  {"state": "not_home",  "attributes": {"friendly_name": "Lisa"},  "domain": "person"},
}


# ─── Tool stubs ────────────────────────────────────────────────────────────────
def _exec_tool(call: dict) -> str:
    name = call.get("name", "")
    try:
        if name == "get_entity_state":
            eid = call.get("entity_id", "")
            ent = SIM_ENTITIES.get(eid)
            if not ent:
                return json.dumps({"error": "entity_not_found", "entity_id": eid,
                                   "hint": "Use search_entities or get_area_entities to find the correct entity_id"})
            return json.dumps({eid: {"state": ent["state"], **ent.get("attributes", {})}})

        elif name == "get_area_entities":
            area = call.get("area", "")
            domain = call.get("domain")
            result = {
                eid: {"state": e["state"], **e.get("attributes", {})}
                for eid, e in SIM_ENTITIES.items()
                if e.get("area_id") == area and (domain is None or e.get("domain") == domain)
            }
            if not result:
                return json.dumps({"error": f"No entities in area '{area}'",
                                   "valid_areas": [a["area_id"] for a in SIM_AREAS]})
            return json.dumps(result)

        elif name in ("search_entities", "search_entity"):
            query = call.get("query", "")
            queries = call.get("queries") or ([query] if query else [])
            result: dict = {}
            for q in queries:
                ql = q.lower()
                for eid, ent in SIM_ENTITIES.items():
                    fname = ent.get("attributes", {}).get("friendly_name", "").lower()
                    if ql in eid.lower() or ql in fname or ql in ent.get("area_id", "").lower():
                        result[eid] = {"state": ent["state"], **ent.get("attributes", {})}
            return json.dumps(result or {"info": "No entities found", "query": query})

        elif name == "get_areas":
            return json.dumps(SIM_AREAS)

        elif name == "list_entities_by_domain":
            d = call.get("domain", "")
            r = {eid: {"state": e["state"], **e.get("attributes", {})}
                 for eid, e in SIM_ENTITIES.items() if e.get("domain") == d}
            return json.dumps(r or {"info": f"No entities for domain '{d}'"})

        elif name == "search_knowledge":
            if not _MEMORY_ENABLED:
                return json.dumps([])   # no memory mode: store is empty
            q = call.get("query", "").lower()
            facts = [
                "light.0x001788010416871a is the werkamer bureaulamp, can be controlled directly",
                "Peter and Lisa live here. Peter is currently home.",
                "switch.koffiezetapparaat is the coffee machine in the keuken area",
                "media_player.woonkamer_tv is the main TV in the woonkamer",
                "climate.woonkamer controls the central heating, currently heating to 21°C",
            ]
            hits = [{"fact": f} for f in facts if any(w in f.lower() for w in q.split() if len(w) > 2)]
            return json.dumps(hits or [{"fact": "No relevant facts found"}])

        elif name == "get_domain_docs":
            d = call.get("domain", "")
            docs = {
                "light":        {"services": ["turn_on(brightness, rgb_color, color_temp)", "turn_off()", "toggle()"]},
                "climate":      {"services": ["set_temperature(temperature)", "set_hvac_mode(hvac_mode)", "turn_off()"]},
                "media_player": {"services": ["turn_on()", "turn_off()", "media_pause()", "media_play()", "select_source(source)"]},
                "switch":       {"services": ["turn_on()", "turn_off()", "toggle()"]},
                "automation":   {"services": ["trigger()", "turn_on()", "turn_off()", "reload()"]},
                "person":       {"note": "Read-only sensor. State is 'home' or 'not_home'."},
            }
            return json.dumps(docs.get(d, {"error": f"No docs for '{d}'"}))

        elif name == "list_entities_without_area":
            r = {eid: {"state": e["state"], **e.get("attributes", {})}
                 for eid, e in SIM_ENTITIES.items() if "area_id" not in e}
            return json.dumps(r or {"info": "All entities have areas assigned"})

        elif name in ("get_labels", "list_entities_by_label"):
            return json.dumps([] if name == "get_labels" else {"info": "No labels configured"})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─── Test scenarios ────────────────────────────────────────────────────────────
# Check types:
#   ("tool_called", name)            model called this tool at any point
#   ("plan_service", "dom.svc")      plan block has an action with this service
#   ("plan_exists",)                 any plan block was produced
#   ("plan_contains_value", val)     plan JSON text contains this value
#   ("no_plan",)                     should be chat, NOT a plan
#   ("response_contains", text)      final response text contains substring
#   ("response_contains_one_of", []) final response contains any substring in list
#   ("state_read", entity_id)        get_entity_state was called for this entity
TEST_SCENARIOS: list[dict] = [
    {
        "id": "lights_off_werkamer",
        "user": "Doe de lichten in de werkamer uit",
        "description": "Turn off werkamer lights using get_area_entities, never guess entity IDs",
        "expect_type": "action",
        "checks": [
            ("tool_called", "get_area_entities"),
            ("plan_service", "light.turn_off"),
        ],
    },
    {
        "id": "outside_temp",
        "user": "Hoe warm is het buiten?",
        "description": "Query outside temperature sensor, answer in chat (no plan)",
        "expect_type": "chat",
        "checks": [
            ("no_plan",),
            ("response_contains", "14"),
        ],
    },
    {
        "id": "set_thermostat_21",
        "user": "Zet de verwarming op 21 graden",
        "description": "Set woonkamer thermostat to 21°C via plan",
        "expect_type": "action",
        "checks": [
            ("plan_service", "climate.set_temperature"),
            ("plan_contains_value", "21"),
        ],
    },
    {
        "id": "is_peter_home",
        "user": "Is Peter thuis?",
        "description": "Check person presence, answer in chat (no plan needed)",
        "expect_type": "chat",
        "checks": [
            ("no_plan",),
            ("response_contains_one_of", ["thuis", "home", "ja", "yes", "aanwezig"]),
        ],
    },
    {
        "id": "lights_on_keuken",
        "user": "Zet de keuken lampen aan",
        "description": "Turn on keuken lights using get_area_entities, not guessed IDs",
        "expect_type": "action",
        "checks": [
            ("tool_called", "get_area_entities"),
            ("plan_service", "light.turn_on"),
        ],
    },
    {
        "id": "tv_off_woonkamer",
        "user": "Zet de televisie in de woonkamer uit",
        "description": "Turn off woonkamer TV via plan (media_player.turn_off)",
        "expect_type": "action",
        "checks": [
            ("plan_service", "media_player.turn_off"),
        ],
    },
    {
        "id": "what_is_on_woonkamer",
        "user": "Wat staat er aan in de woonkamer?",
        "description": "List active entities in woonkamer using get_area_entities, answer in chat",
        "expect_type": "chat",
        "checks": [
            ("tool_called", "get_area_entities"),
            ("no_plan",),
        ],
    },
    {
        "id": "coffee_off",
        "user": "Zet het koffiezetapparaat uit",
        "description": "Turn off coffee maker (switch.turn_off) via plan",
        "expect_type": "action",
        "checks": [
            ("plan_service", "switch.turn_off"),
        ],
    },
    {
        "id": "all_lights_off",
        "user": "Doe alle lichten in huis uit",
        "description": "Turn off all lights in every area via plan",
        "expect_type": "action",
        "checks": [
            ("plan_exists",),
            ("plan_contains_value", "turn_off"),
        ],
    },
    {
        "id": "morning_automation",
        "user": "Maak een automatisering die elke dag om 7:30 de gang lamp aanzet",
        "description": "Create morning automation for gang light at 7:30",
        "expect_type": "action",
        "checks": [
            ("plan_exists",),
        ],
    },
    # ── Real-home scenarios (from kyber-home-state export) ──────────────────
    {
        "id": "waar_is_peter",
        "user": "Waar is Peter?",
        "description": "Location query — person.peter=home, respond in Dutch, no plan needed",
        "expect_type": "chat",
        "checks": [
            ("no_plan",),
            ("state_read", "person.peter"),
            ("response_contains_one_of", ["thuis", "home", "aanwezig"]),
        ],
    },
    {
        "id": "peter_in_werkkamer",
        "user": "Waar is Peter precies?",
        "description": "Room-level location — binary_sensor.presence_werkkamer_304_presence=on means Peter is in werkkamer",
        "expect_type": "chat",
        "checks": [
            ("no_plan",),
            ("response_contains", "werkkamer"),
        ],
    },
    {
        "id": "koffie_espresso",
        "user": "Ik wil koffie",
        "description": "Turn on espresso machine: switch.0xa4c138d5f4f912f2 (onoff_keuken_espresso_304). NOT the lamp or status input_texts.",
        "expect_type": "action",
        "checks": [
            ("plan_service", "switch.turn_on"),
            ("plan_contains_value", "0xa4c138d5f4f912f2"),
        ],
    },
]


# ─── Ollama client ─────────────────────────────────────────────────────────────
def ollama_call(model: str, prompt: str, url: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens,
                    "stop": ["\n\nUser:", "\n\nHuman:"]},
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read()).get("response", "")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama unreachable at {url}: {e}") from e


# ─── Instructions builder ─────────────────────────────────────────────────────
_NOTABLE = (
    "\n### Current Home State (notable only)\n"
    "**Woonkamer:** light.woonkamer_lamp ON, media_player.woonkamer_tv PLAYING (Netflix), "
    "climate.woonkamer HEATING → 21°C\n"
    "**Werkamer:** light.0x001788010416871a ON\n"
    "**Keuken:** switch.koffiezetapparaat ON\n"
)


def _safe_format(template: str, **kwargs) -> str:
    """Replace only known placeholders via str.replace, then unescape {{ / }}.

    Python's str.format() trips on literal JSON braces like {"area_id": ...}
    that appear in the prompt's tool-call examples.  This avoids that entirely.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    # Unescape double-braces that were escaped in const.py for Python's format()
    result = result.replace("{{", "{").replace("}}", "}")
    return result


def build_instructions(template: str, user_msg: str) -> str:
    areas_block = "\n**Areas:** " + ", ".join(
        f"{a['name']} ({a['area_id']})" for a in SIM_AREAS
    )
    try:
        ctx = _safe_format(
            template,
            home_summary="**Home:** 6 areas · 0 labels · 0 automations · 0 scripts · "
                         "13 entities (light:6, climate:1, sensor:2, media_player:1, switch:1, person:2)",
            areas_block=areas_block,
            timezone_block="**Timezone:** Europe/Amsterdam — display all times in this timezone, not UTC.\n",
            notable_state_block=_NOTABLE,
        )
    except Exception as e:
        raise RuntimeError(f"Prompt formatting failed: {e}") from e

    # Pre-inject relevant knowledge facts (simulates Kyber's semantic-search injection).
    # Skipped in no-memory mode so we can measure how much the model relies on it.
    if _MEMORY_ENABLED:
        user_lo = user_msg.lower()
        injected: list[str] = []
        for kw, facts in _KNOWLEDGE_FACTS.items():
            if kw in user_lo:
                injected.extend(facts)
        if injected:
            facts_block = "\n## Relevant knowledge\n" + "\n".join(f"- {f}" for f in injected) + "\n"
            ctx = ctx + facts_block

    return ctx + f"\n\nUser: {user_msg}\n\nAssistant:"


# ─── AI loop ───────────────────────────────────────────────────────────────────
@dataclass
class LoopResult:
    final_response: str
    tool_calls_made: list[dict] = field(default_factory=list)
    plan_block: Optional[dict] = None
    full_transcript: str = ""
    rounds: int = 0


def run_loop(model: str, ollama_url: str, instructions: str, no_think: bool = False) -> LoopResult:
    MAX_ROUNDS = 5
    if no_think:
        instructions = "/no_think\n" + instructions

    tool_exchange = ""
    all_calls: list[dict] = []
    plan_block: Optional[dict] = None
    response_text = ""

    for rnd in range(MAX_ROUNDS):
        prompt = instructions + tool_exchange
        response_text = ollama_call(model, prompt, ollama_url)

        if "<think>" in response_text:
            response_text = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL).strip()

        # Normalize ```json {...}``` → ```plan {...}``` (same step real Kyber does)
        if _normalize_json_plan_blocks:
            response_text = _normalize_json_plan_blocks(response_text)
        if _rewrap_bare_action_fences:
            response_text = _rewrap_bare_action_fences(response_text)

        pb = _extract_plan_block(response_text)
        if pb and not plan_block:
            plan_block = pb

        tool_calls = _parse_tool_calls(response_text)
        if not tool_calls:
            break

        # Dedup
        seen: set[str] = set()
        unique: list[dict] = []
        for c in tool_calls:
            sig = json.dumps({"n": c.get("name"), "a": {k: v for k, v in c.items() if k != "name"}}, sort_keys=True)
            if sig not in seen:
                seen.add(sig)
                unique.append(c)

        if not unique:
            break

        clean = _strip_tool_calls(response_text)
        results_block = ""
        for c in unique:
            all_calls.append({"name": c.get("name", ""), "args": {k: v for k, v in c.items() if k != "name"}})
            res = _exec_tool(c)
            results_block += f"\n[TOOL_RESULT: {json.dumps(c)}]\n{res}\n"

        tool_exchange += f"{clean}\n{results_block}\nAssistant:"

    if not plan_block:
        plan_block = _extract_plan_block(response_text)

    return LoopResult(
        final_response=_strip_tool_calls(response_text).strip(),
        tool_calls_made=all_calls,
        plan_block=plan_block,
        full_transcript=instructions + tool_exchange + response_text,
        rounds=rnd + 1,
    )


# ─── Structural grader ─────────────────────────────────────────────────────────
@dataclass
class Grade:
    struct_score: float     # 0-10
    llm_score: Optional[float] = None
    issues: list[str] = field(default_factory=list)
    llm_notes: str = ""

    @property
    def final_score(self) -> float:
        s = self.struct_score
        if self.llm_score is not None:
            s = 0.4 * s + 0.6 * self.llm_score
        return round(s, 1)

    @property
    def icon(self) -> str:
        f = self.final_score
        return "✅" if f >= 7 else ("⚠️" if f >= 4 else "❌")


def _grade_structural(scenario: dict, result: LoopResult) -> Grade:
    plan_text = json.dumps(result.plan_block) if result.plan_block else ""
    plan_actions: list[dict] = result.plan_block.get("actions", []) if result.plan_block else []
    # Flatten nested plan actions: {"plan": [...]} → [...]
    flat_actions: list[dict] = []
    for a in plan_actions:
        if isinstance(a, dict) and "plan" in a and isinstance(a["plan"], list):
            flat_actions.extend(a["plan"])
        else:
            flat_actions.append(a)
    # Build both bare service names and full "domain.service" strings
    all_services: list[str] = []
    for a in flat_actions:
        svc = str(a.get("service", a.get("type", "")))
        dom = str(a.get("domain", ""))
        all_services.append(svc)
        if dom and svc:
            all_services.append(f"{dom}.{svc}")
    tool_names = [t["name"] for t in result.tool_calls_made]
    resp_lo = result.final_response.lower()

    issues: list[str] = []
    passes = 0

    for chk in scenario.get("checks", []):
        kind = chk[0]
        ok = False
        if kind == "tool_called":
            ok = chk[1] in tool_names
            if not ok:
                issues.append(f"tool '{chk[1]}' not called (called: {tool_names})")
        elif kind == "plan_service":
            svc = chk[1]
            ok = any(svc in s for s in all_services)
            if not ok:
                # Also check raw plan text for flexibility
                ok = svc in plan_text
            if not ok and "." in svc:
                # "light.turn_off" → check entity_id (or target) starts with "light." AND service == "turn_off"
                dom_prefix, svc_name = svc.split(".", 1)
                for a in flat_actions:
                    # model sometimes uses "target" instead of "entity_id"
                    eid = str(a.get("entity_id", a.get("target", "")))
                    if a.get("service") == svc_name and eid.startswith(f"{dom_prefix}."):
                        ok = True
                        break
            if not ok:
                issues.append(f"service '{svc}' not in plan (got: {all_services})")
        elif kind == "plan_exists":
            ok = result.plan_block is not None
            if not ok:
                issues.append("no plan block produced")
        elif kind == "plan_contains_value":
            ok = chk[1] in plan_text
            if not ok:
                issues.append(f"plan missing value '{chk[1]}'")
        elif kind == "no_plan":
            ok = result.plan_block is None
            if not ok:
                issues.append(f"chat expected but got plan: {plan_text[:80]}")
        elif kind == "response_contains":
            ok = chk[1].lower() in resp_lo
            if not ok:
                issues.append(f"response missing '{chk[1]}'")
        elif kind == "response_contains_one_of":
            ok = any(v.lower() in resp_lo for v in chk[1])
            if not ok:
                issues.append(f"response missing one of {chk[1]}")
        elif kind == "state_read":
            ok = any(t["name"] == "get_entity_state" and t["args"].get("entity_id") == chk[1]
                     for t in result.tool_calls_made)
            if not ok:
                issues.append(f"get_entity_state('{chk[1]}') not called")
        if ok:
            passes += 1

    total = max(1, passes + len(issues))
    return Grade(struct_score=round(passes / total * 10, 1), issues=issues)


def _grade_llm(model: str, url: str, scenario: dict, result: LoopResult) -> tuple[float, str]:
    tools_used = ", ".join(t["name"] for t in result.tool_calls_made) or "none"
    plan_s = json.dumps(result.plan_block)[:300] if result.plan_block else "none"
    resp_s = result.final_response[:350]

    prompt = f"""/no_think
You are a strict evaluator. Rate this Home Assistant AI response 0-10.
10=perfect, 7-9=good, 4-6=partial, 0-3=wrong/harmful.

User: "{scenario['user']}"
Expected: {scenario['description']}
Expect type: {scenario['expect_type']} (action=plan block required, chat=text answer only)

Tools called: {tools_used}
Plan: {plan_s}
Response: {resp_s}

Reply ONLY with JSON (no explanation outside JSON):
{{"score": 8, "issues": ["issue if any"]}}"""

    try:
        raw = ollama_call(model, prompt, url, temperature=0.0, max_tokens=200)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        m = re.search(r'\{\s*"score"\s*:\s*(\d+(?:\.\d+)?)[^}]*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            score = float(max(0, min(10, data.get("score", 5))))
            notes = "; ".join(data.get("issues", [])) or "OK"
            return score, notes
    except Exception:
        pass
    return 5.0, "judge error"


# ─── Improvement engine ────────────────────────────────────────────────────────
def _analyze_and_improve(
    model: str, url: str,
    failures: list[tuple[dict, LoopResult, Grade]],
    prompt: str,
) -> tuple[str, str, str]:
    """Return (improved_prompt, diagnosis, change_description)."""
    if not failures:
        return prompt, "no failures", "none"

    # Extract Quick recipes section for context
    rs = prompt.find("### Quick recipes")
    re_ = prompt.find("\n##", rs + 1) if rs != -1 else -1
    recipes_ctx = prompt[rs:re_][:3000] if rs != -1 else "(not found)"

    fail_text = ""
    for sc, res, gr in failures[:4]:
        tools = [t["name"] for t in res.tool_calls_made]
        plan_s = json.dumps(res.plan_block)[:200] if res.plan_block else "none"
        fail_text += (
            f"\n[FAIL] {sc['id']}: \"{sc['user']}\"\n"
            f"  Expected: {sc['description']}\n"
            f"  Tools used: {tools}\n"
            f"  Plan: {plan_s}\n"
            f"  Issues: {'; '.join(gr.issues[:3])}\n"
            f"  Response: {res.final_response[:150]}\n"
        )

    analysis_prompt = f"""/no_think
You improve a Home Assistant AI assistant's system prompt.
Below are test failures. Diagnose the ROOT CAUSE and write ONE new quick-recipe bullet
that would fix the most failures. Keep it concrete (≤2 lines).

Current Quick recipes:
---
{recipes_ctx}
---

Failures:
{fail_text}

Reply ONLY with JSON:
{{"diagnosis": "root cause in 1 sentence", "new_recipe": "- Turn off <X> → ALWAYS ... (concrete instruction)"}}"""

    try:
        raw = ollama_call(model, analysis_prompt, url, temperature=0.15, max_tokens=400)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        m = re.search(r'\{\s*"diagnosis"[^}]*"new_recipe"[^}]*\}', raw, re.DOTALL)
        if not m:
            m = re.search(r'\{[\s\S]+?\}', raw)
        if m:
            data = json.loads(m.group(0))
            diag = str(data.get("diagnosis", "")).strip()
            recipe = str(data.get("new_recipe", "")).strip()
            if recipe and len(recipe) > 15:
                # Prepend to Quick recipes section
                marker = "### Quick recipes\n"
                if marker in prompt:
                    insert_at = prompt.find(marker) + len(marker)
                    if not recipe.startswith("- "):
                        recipe = f"- {recipe}"
                    new_prompt = prompt[:insert_at] + recipe + "\n" + prompt[insert_at:]
                    return new_prompt, diag, recipe
    except Exception as exc:
        return prompt, f"analysis error: {exc}", "none"

    return prompt, "inconclusive", "none"


# ─── Iteration runner ──────────────────────────────────────────────────────────
@dataclass
class IterResult:
    iteration: int
    scores: dict[str, float]   # scenario_id → final score
    avg: float
    passes: int                # score ≥ 7
    change: str = ""
    diagnosis: str = ""


def run_iteration(
    iteration: int, model: str, url: str,
    prompt: str, use_judge: bool,
) -> tuple[list[tuple[dict, LoopResult, Grade]], IterResult]:
    width = 60
    print(f"\n{'═'*width}")
    print(f"  RUN {iteration + 1}  ({len(TEST_SCENARIOS)} scenarios)")
    print(f"{'═'*width}")

    scored: list[tuple[dict, LoopResult, Grade]] = []
    for sc in TEST_SCENARIOS:
        print(f"  {sc['id']:<28}", end="", flush=True)
        t0 = time.time()
        instructions = build_instructions(prompt, sc["user"])
        result = run_loop(model, url, instructions, no_think="qwen3" in model.lower())
        grade = _grade_structural(sc, result)

        if use_judge:
            lscore, lnotes = _grade_llm(model, url, sc, result)
            grade.llm_score = lscore
            grade.llm_notes = lnotes

        elapsed = time.time() - t0
        issues_str = ("; ".join(grade.issues[:2]) or grade.llm_notes or "")[:55]
        print(f"{grade.icon} {grade.final_score:4.1f}  {issues_str}  [{elapsed:.0f}s]")
        scored.append((sc, result, grade))

    scores = {sc["id"]: g.final_score for sc, _, g in scored}
    avg = round(sum(scores.values()) / len(scores), 1)
    passes = sum(1 for v in scores.values() if v >= 7)
    print(f"\n  {'─'*40}")
    print(f"  Avg: {avg:.1f}/10   Pass (≥7): {passes}/{len(TEST_SCENARIOS)}")

    return scored, IterResult(iteration=iteration, scores=scores, avg=avg, passes=passes)


# ─── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Kyber prompt eval & auto-improve")
    ap.add_argument("--model",      default="qwen3:4b-instruct")
    ap.add_argument("--iterations", type=int, default=5)
    ap.add_argument("--ollama",     default="http://localhost:11434")
    ap.add_argument("--no-judge",   action="store_true", help="Skip LLM judge (much faster)")
    ap.add_argument("--save-prompt",action="store_true", help="Write best prompt back to const.py")
    args = ap.parse_args()

    print(f"\nKyber Prompt Eval — model={args.model}  iter={args.iterations}  judge={'off' if args.no_judge else 'on'}")

    # Verify Ollama is reachable
    try:
        ollama_call(args.model, "hi", args.ollama, max_tokens=5)
    except RuntimeError as e:
        print(f"\n❌ {e}\nMake sure Ollama is running and '{args.model}' is pulled.")
        sys.exit(1)

    current_prompt = _BASE_PROMPT
    iter_results: list[IterResult] = []
    change_log: list[dict] = []

    for i in range(args.iterations):
        scored, ir = run_iteration(i, args.model, args.ollama, current_prompt, not args.no_judge)

        # Analyze failures and improve for NEXT iteration
        if i < args.iterations - 1:
            failures = [(sc, res, gr) for sc, res, gr in scored if gr.final_score < 7]
            if failures:
                print(f"\n  Analyzing {len(failures)} failures → generating improvement…")
                new_prompt, diag, change = _analyze_and_improve(args.model, args.ollama, failures, current_prompt)
                ir.change = change
                ir.diagnosis = diag
                if new_prompt != current_prompt:
                    current_prompt = new_prompt
                    print(f"  ✏️  Applied: {change[:80]}")
                    change_log.append({
                        "after_run": i + 1,
                        "diagnosis": diag,
                        "change": change,
                        "failing_tests": [sc["id"] for sc, _, gr in failures],
                        "score_before": ir.avg,
                    })
                else:
                    print("  ℹ️  No change (analysis inconclusive)")
            else:
                ir.change = "(all passed)"
        else:
            ir.change = "(final run)"

        iter_results.append(ir)
        # Tag score_after for change_log entries
        if change_log and "score_after" not in change_log[-1]:
            change_log[-1]["score_after"] = ir.avg

    # ─── Final report ─────────────────────────────────────────────────────────
    print(f"\n\n{'═'*70}")
    print("  SCORE TABLE  (per scenario per run)")
    print(f"{'═'*70}")

    COL = 26
    hdrs = "".join(f"  Run{r.iteration+1:>2}" for r in iter_results)
    print(f"\n  {'Scenario':<{COL}}{hdrs}")
    print(f"  {'─'*COL}" + "────────" * len(iter_results))

    for sc in TEST_SCENARIOS:
        sid = sc["id"]
        cells = ""
        for r in iter_results:
            v = r.scores.get(sid, 0.0)
            icon = "✅" if v >= 7 else ("⚠️" if v >= 4 else "❌")
            cells += f" {icon}{v:3.1f} "
        print(f"  {sid:<{COL}}{cells}")

    print(f"  {'─'*COL}" + "────────" * len(iter_results))
    avg_row = "".join(f"  {r.avg:>5.1f} " for r in iter_results)
    print(f"  {'AVG SCORE':<{COL}}{avg_row}")
    pass_row = "".join(f"  {r.passes:>4}/{len(TEST_SCENARIOS)} " for r in iter_results)
    print(f"  {'PASS ≥7':<{COL}}{pass_row}")

    print(f"\n\n{'═'*70}")
    print("  IMPROVEMENT LOG  (what was learned and applied between runs)")
    print(f"{'═'*70}")

    if not change_log:
        print("\n  No improvements applied (all tests passed or analysis inconclusive).")
    else:
        for entry in change_log:
            before = entry.get("score_before", "?")
            after  = entry.get("score_after", "?")
            try:
                delta = float(after) - float(before)
                effect = f"{before:.1f} → {after:.1f}  ({'+' if delta >= 0 else ''}{delta:.1f})"
            except (TypeError, ValueError):
                effect = f"{before} → {after}"
            print(f"\n  After run {entry['after_run']}  →  used in run {entry['after_run']+1}:")
            print(f"    Failing tests  : {', '.join(entry['failing_tests'])}")
            print(f"    Diagnosis      : {entry['diagnosis'][:120]}")
            print(f"    Change applied : {entry['change'][:120]}")
            print(f"    Score effect   : {effect}")

    # Save JSON results
    out_dir = ROOT / "scripts" / "eval_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"eval_{int(time.time())}.json"
    out_file.write_text(json.dumps({
        "model": args.model,
        "iterations": args.iterations,
        "runs": [
            {"run": r.iteration + 1, "scores": r.scores, "avg": r.avg,
             "passes": r.passes, "change": r.change}
            for r in iter_results
        ],
        "change_log": change_log,
    }, indent=2), encoding="utf-8")
    print(f"\n  Results saved → {out_file.relative_to(ROOT)}")

    if args.save_prompt:
        _write_improved_prompt(current_prompt)
        print("  Improved prompt written to const.py  (www/ sync needed)")

    print()


def _save_json_results(
    iter_results: list[IterResult],
    change_log: list[dict],
    model: str,
    iterations: int,
    suffix: str = "",
) -> None:
    out_dir = ROOT / "scripts" / "eval_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"eval_{int(time.time())}{suffix}.json"
    out_file.write_text(json.dumps({
        "model": model, "iterations": iterations,
        "runs": [{"run": r.iteration + 1, "scores": r.scores, "avg": r.avg,
                  "passes": r.passes, "change": r.change} for r in iter_results],
        "change_log": change_log,
    }, indent=2), encoding="utf-8")
    print(f"\n  Results saved → {out_file.relative_to(ROOT)}")


# ─── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Kyber prompt eval & auto-improve")
    ap.add_argument("--model",       default="qwen3:4b-instruct")
    ap.add_argument("--iterations",  type=int, default=5)
    ap.add_argument("--ollama",      default="http://localhost:11434")
    ap.add_argument("--no-judge",    action="store_true", help="Skip LLM judge (much faster)")
    ap.add_argument("--compare",     action="store_true", help="With vs without memory — 3 runs each, side-by-side table")
    ap.add_argument("--save-prompt", action="store_true", help="Write best prompt back to const.py")
    args = ap.parse_args()

    print(f"\nKyber Prompt Eval — model={args.model}  judge={'off' if args.no_judge else 'on'}")

    try:
        ollama_call(args.model, "hi", args.ollama, max_tokens=5)
    except RuntimeError as e:
        print(f"\n❌ {e}\nMake sure Ollama is running and '{args.model}' is pulled.")
        sys.exit(1)

    if args.compare:
        _run_comparison(args.model, args.ollama, not args.no_judge)
        return

    # ── Normal improvement loop ───────────────────────────────────────────────
    global _MEMORY_ENABLED
    _MEMORY_ENABLED = True
    current_prompt = _BASE_PROMPT
    iter_results: list[IterResult] = []
    change_log: list[dict] = []

    for i in range(args.iterations):
        scored, ir = run_iteration(i, args.model, args.ollama, current_prompt, not args.no_judge)

        if i < args.iterations - 1:
            failures = [(sc, res, gr) for sc, res, gr in scored if gr.final_score < 7]
            if failures:
                print(f"\n  Analyzing {len(failures)} failures → generating improvement…")
                new_prompt, diag, change = _analyze_and_improve(args.model, args.ollama, failures, current_prompt)
                ir.change = change
                ir.diagnosis = diag
                if new_prompt != current_prompt:
                    current_prompt = new_prompt
                    print(f"  ✏️  Applied: {change[:80]}")
                    change_log.append({
                        "after_run": i + 1, "diagnosis": diag, "change": change,
                        "failing_tests": [sc["id"] for sc, _, gr in failures],
                        "score_before": ir.avg,
                    })
                else:
                    print("  ℹ️  No change (analysis inconclusive)")
            else:
                ir.change = "(all passed)"
        else:
            ir.change = "(final run)"

        iter_results.append(ir)
        if change_log and "score_after" not in change_log[-1]:
            change_log[-1]["score_after"] = ir.avg

    # ── Score table ───────────────────────────────────────────────────────────
    print(f"\n\n{'═'*70}")
    print("  SCORE TABLE  (per scenario per run, with memory ON)")
    print(f"{'═'*70}")
    COL = 26
    hdrs = "".join(f"  Run{r.iteration+1:>2}" for r in iter_results)
    print(f"\n  {'Scenario':<{COL}}{hdrs}")
    print(f"  {'─'*COL}" + "────────" * len(iter_results))
    for sc in TEST_SCENARIOS:
        sid = sc["id"]
        cells = "".join(
            f" {'✅' if v >= 7 else ('⚠️' if v >= 4 else '❌')}{v:3.1f} "
            for v in (r.scores.get(sid, 0.0) for r in iter_results)
        )
        print(f"  {sid:<{COL}}{cells}")
    print(f"  {'─'*COL}" + "────────" * len(iter_results))
    print(f"  {'AVG SCORE':<{COL}}" + "".join(f"  {r.avg:>5.1f} " for r in iter_results))
    print(f"  {'PASS ≥7':<{COL}}" + "".join(f"  {r.passes:>4}/{len(TEST_SCENARIOS)} " for r in iter_results))

    # ── Improvement log ───────────────────────────────────────────────────────
    print(f"\n\n{'═'*70}")
    print("  IMPROVEMENT LOG")
    print(f"{'═'*70}")
    if not change_log:
        print("\n  No improvements applied.")
    else:
        for entry in change_log:
            before, after = entry.get("score_before","?"), entry.get("score_after","?")
            try:
                delta = float(after) - float(before)
                eff = f"{before:.1f} → {after:.1f}  ({'+' if delta >= 0 else ''}{delta:.1f})"
            except (TypeError, ValueError):
                eff = f"{before} → {after}"
            print(f"\n  After run {entry['after_run']}:")
            print(f"    Failing tests  : {', '.join(entry['failing_tests'])}")
            print(f"    Diagnosis      : {entry['diagnosis'][:120]}")
            print(f"    Change applied : {entry['change'][:120]}")
            print(f"    Score effect   : {eff}")

    _save_json_results(iter_results, change_log, args.model, args.iterations)
    if args.save_prompt:
        _write_improved_prompt(current_prompt)
        print("  Improved prompt written to const.py  (www/ sync needed)")
    print()


def _run_comparison(model: str, url: str, use_judge: bool, runs: int = 3) -> None:
    """3 passes without memory vs 3 with memory; print side-by-side comparison."""
    global _MEMORY_ENABLED
    prompt = _BASE_PROMPT

    print(f"\n{'═'*70}")
    print(f"  MEMORY COMPARISON  ({runs} runs each, no prompt improvement)")
    print(f"{'═'*70}")

    def _do_runs(memory: bool) -> list[dict[str, float]]:
        global _MEMORY_ENABLED
        _MEMORY_ENABLED = memory
        return [run_iteration(i, model, url, prompt, use_judge)[1].scores for i in range(runs)]

    print(f"\n  ── WITHOUT MEMORY {'─'*43}")
    no_mem = _do_runs(False)
    print(f"\n  ── WITH MEMORY {'─'*45}")
    with_mem = _do_runs(True)

    def _avg(runs_list: list[dict], sid: str) -> float:
        vals = [s.get(sid, 0.0) for s in runs_list]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    # ── Comparison table ──────────────────────────────────────────────────────
    print(f"\n\n{'═'*82}")
    print("  WITH MEMORY  vs  WITHOUT MEMORY   (averaged over 3 runs each)")
    print(f"{'═'*82}")
    print(f"\n  {'Scenario':<28}  {'No Mem':>8}  {'W/ Mem':>8}  {'Δ':>6}  Verdict")
    print(f"  {'─'*28}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*30}")

    verdicts: list[tuple[str, float, float]] = []
    for sc in TEST_SCENARIOS:
        sid = sc["id"]
        nm = _avg(no_mem,   sid)
        wm = _avg(with_mem, sid)
        d  = wm - nm
        sign = "+" if d >= 0 else ""
        nm_ic = "✅" if nm >= 7 else ("⚠️" if nm >= 4 else "❌")
        wm_ic = "✅" if wm >= 7 else ("⚠️" if wm >= 4 else "❌")

        if   d >= 2.5:              verdict = "📚 needs memory"
        elif d <= -2.5:             verdict = "🤔 worse with memory"
        elif nm >= 7 and wm >= 7:   verdict = "✨ works either way"
        elif nm < 4  and wm < 4:    verdict = "🔴 broken both ways"
        else:                       verdict = "~ marginal"

        print(f"  {sid:<28}  {nm_ic}{nm:>6.1f}  {wm_ic}{wm:>6.1f}  {sign}{d:>5.1f}  {verdict}")
        verdicts.append((sid, nm, wm))

    print(f"  {'─'*28}  {'─'*8}  {'─'*8}  {'─'*6}")
    tnm = round(sum(n for _,n,_ in verdicts)/len(verdicts), 1)
    twm = round(sum(w for _,_,w in verdicts)/len(verdicts), 1)
    td  = twm - tnm
    print(f"  {'AVG':<28}  {tnm:>10.1f}  {twm:>8.1f}  {'+' if td>=0 else ''}{td:>5.1f}")

    # ── Narrative findings ────────────────────────────────────────────────────
    needs_mem  = [(s,n,w) for s,n,w in verdicts if (w-n) >= 2.5]
    works_both = [(s,n,w) for s,n,w in verdicts if n >= 7 and w >= 7]
    broken     = [(s,n,w) for s,n,w in verdicts if n < 4 and w < 4]
    worse_mem  = [(s,n,w) for s,n,w in verdicts if (n-w) >= 2.5]
    partial_nm = [(s,n,w) for s,n,w in verdicts if 4 <= n < 7 and w >= 7]

    print(f"\n\n{'═'*70}")
    print("  FINDINGS")
    print(f"{'═'*70}")

    if works_both:
        print(f"\n  ✨ Works fine without memory  ({len(works_both)} scenarios):")
        for s,n,w in works_both:
            print(f"     · {s:<28}  no-mem {n:.1f}  w/mem {w:.1f}")
        print("     → Prompt + areas_block alone is enough for these.")

    if needs_mem:
        print(f"\n  📚 Needs memory to work  ({len(needs_mem)} scenarios):")
        for s,n,w in needs_mem:
            print(f"     · {s:<28}  no-mem {n:.1f} → w/mem {w:.1f}  (+{w-n:.1f})")
        print("     → Model relies on pre-injected facts or search_knowledge results.")

    if partial_nm:
        print(f"\n  ⚠️  Works partially without, fully with memory  ({len(partial_nm)}):")
        for s,n,w in partial_nm:
            print(f"     · {s:<28}  no-mem {n:.1f} → w/mem {w:.1f}")

    if broken:
        print(f"\n  🔴 Broken regardless of memory  ({len(broken)} scenarios):")
        for s,n,w in broken:
            print(f"     · {s:<28}  no-mem {n:.1f}  w/mem {w:.1f}")
        print("     → Prompt itself needs improvement for these — memory alone won't help.")

    if worse_mem:
        print(f"\n  🤔 Worse WITH memory  ({len(worse_mem)} scenarios):")
        for s,n,w in worse_mem:
            print(f"     · {s:<28}  no-mem {n:.1f} → w/mem {w:.1f}  ({w-n:.1f})")
        print("     → Injected facts may be confusing the model or causing over-reliance.")

    print()

    all_results = [IterResult(i, r, round(sum(r.values())/len(r),1),
                              sum(1 for v in r.values() if v >= 7))
                   for i, r in enumerate(no_mem + with_mem)]
    _save_json_results(all_results, [], model, runs * 2, suffix="_memory_comparison")


def _write_improved_prompt(improved: str) -> None:
    const_path = ROOT / "custom_components/kyber/const.py"
    src = const_path.read_text(encoding="utf-8")
    start = src.find('SYSTEM_PROMPT_TEMPLATE = """')
    open_end = src.find('"""', start) + 3
    close = src.find('\n"""', open_end)
    if start == -1 or close == -1:
        raise RuntimeError("Cannot locate SYSTEM_PROMPT_TEMPLATE bounds in const.py")
    const_path.write_text(src[:open_end] + improved + src[close:], encoding="utf-8")


if __name__ == "__main__":
    main()
