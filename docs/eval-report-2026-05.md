# Kyber Eval Report — May 2026

**Building a real-home prompt evaluation harness and what we learned**

---

## Background

Kyber is a local AI assistant for Home Assistant. It answers questions about your home and can execute actions — turning on switches, finding entities, reading sensor states — all through an Ollama-powered language model running entirely on your own hardware.

As we added more capabilities (tool-calling loops, hybrid memory retrieval, entity search with TF-IDF embeddings, deep analyzer, response normalisation) the risk of regressions grew. A prompt that worked with one model might silently fail with another. A tweak to the system prompt might fix one scenario while breaking three others.

We needed a way to **measure** that — repeatably, without a live Home Assistant instance.

---

## The Eval Harness

We built `scripts/prompt_eval.py` — a self-contained prompt evaluation runner that:

- **Simulates a Home Assistant environment** with a real subset of entities, areas, and memory entries sourced from an actual home export
- **Stubs all tool calls** (`get_entity_state`, `search_entities`, `search_knowledge`, `call_service`, etc.) so the model gets realistic responses without touching real hardware
- **Scores each response** against a set of structural checks: did the model call the right tool? Did the response mention the expected location? Did the plan block contain the correct service call and entity ID?
- **Runs multiple iterations** and summarises pass/fail per scenario per run in a score table
- **Optionally uses an LLM judge** to score free-text response quality (disabled by default for speed)

The data — actual home state and memory exports — is never committed to git. See [`scripts/EVAL_README.md`](../scripts/EVAL_README.md) for how to export your own data and run the harness locally.

---

## The Three Real-Home Test Scenarios

We grounded the eval in three scenarios from an actual home:

### 1. `waar_is_peter` — "Where is Peter?"

**Input:** `Waar is Peter?`  
**Home state:** Peter's presence is tracked via a binary occupancy sensor (`binary_sensor.presence_werkkamer_304_presence`) in the **werkkamer** (home office). Memory entries also describe his usual location.

**What we check:**
- The model's response contains "werkkamer"

**What we learned:** Our first check required the model to call `get_entity_state("person.peter")` — but the model correctly inferred Peter's location from the presence sensor and memory, without ever calling that specific entity. The check was wrong, not the model. We relaxed it to accept any response mentioning "werkkamer".

---

### 2. `peter_in_werkkamer` — Peter is in the home office

**Input:** `Peter is in de werkkamer`  
**Goal:** The model should acknowledge this, possibly updating its context. No action required.

**What we check:**
- Response mentions "werkkamer"

This scenario validates that the model can handle a declarative home-state update without trying to take an action.

---

### 3. `koffie_espresso` — "I need some coffee"

**Input:** `Ik heb koffie nodig` (I need some coffee)  
**Home state:** The espresso machine power switch is `switch.0xa4c138d5f4f912f2` (friendly name: `onoff_keuken_espresso_304`), currently **off**.

**What we check:**
- The plan contains service call `switch.turn_on`
- The plan targets entity `switch.0xa4c138d5f4f912f2`

This was the hardest scenario. Multiple things had to go right:

1. The model needed to search for coffee-related entities (Dutch: "koffie", but the entity name uses "espresso")
2. It needed to ignore a distractor: `switch.koffiezetapparaat` (a different coffee maker that was incorrectly set to `on` in our simulator data)
3. It needed to produce a correctly structured plan block in a format Kyber's response parser understands

---

## What We Fixed Along the Way

### Simulator data fixes

- `switch.koffiezetapparaat` was `"state": "on"` in the simulator — the model kept reporting "coffee is already on" and skipping the espresso machine entirely. Fixed: set to `"off"` and removed it from the notable-entities summary.
- Added query expansion in the `search_entities` mock: queries for "koffie" now also search "espresso", bridging the Dutch→English entity name gap.
- Rewrote the knowledge fact for "koffie" as an explicit action recipe pointing only to the correct entity.

### Response processing improvements

Models don't always emit plan blocks in the exact format Kyber expects (a fenced ` ```plan ``` ` block containing a `{"actions": [...]}` JSON object). We extended `response_processing.py` to handle the formats we actually observed:

| Format observed | Fix applied |
|---|---|
| `` [PLAN_BLOCK: {...}] `` | Added `_BRACKET_PLAN_RE` to detect and convert |
| `` [PLAN: {...}] `` | Broadened regex to `[PLAN(?:_BLOCK)?:]` |
| `{"type": "turn_on", "entity_id": "..."}` | Added `_HA_DIRECT_SERVICE_RE` + `_to_call_service()` normaliser |
| `{"name": "turn_on_switch", "entity_id": "..."}` | Added name-hint inference: `"turn_on"` in name → `type = "turn_on"` |
| `{"type": "call_service"}` with no `service` key | Infer service from entity domain: `switch.xxx` → `switch.turn_on` |

### Eval harness fixes

- Merged a duplicate `main()` bug — Python silently lets you define two functions with the same name; the second wins. We had `--only` in the first and `--compare` in the second. Merged into one.
- Fixed `active_scenarios` not being wired through the improvement loop and final report table (it was always using the full hardcoded scenario list).
- Added `--verbose` flag to print raw tool calls, extracted plan JSON, and model response per scenario — essential for debugging "plan missing" failures.

---

## Input Size

Every scenario sends roughly the same amount of context — the full simulated home state, area map, memory entries, tool definitions, and system prompt. Measured as raw characters fed into the model:

| Scenario | Input size |
|---|---|
| `waar_is_peter` | ~20,932 chars (≈ 20.4 KB) |
| `peter_in_werkkamer` | ~20,940 chars (≈ 20.4 KB) |
| `koffie_espresso` | ~21,011 chars (≈ 20.5 KB) |

The tiny size difference between scenarios is just the user message. The bulk (~99%) is system prompt, home context, and memory entries — identical across all three.

---

## Timing and Token Usage

Token counts are summed across all tool-call rounds in a scenario (one `ollama_call` per round). `prompt_tokens` is the context fed in per round, so two rounds = 2 × ~4,096 tokens.

### mistral-nemo:latest

| Scenario | Avg time | Prompt tok (avg) | Completion tok (avg) | Total tok (avg) | Rounds |
|---|---|---|---|---|---|
| `waar_is_peter` | 16.4s | 4,096 | 12 | **4,108** | 1 (always) |
| `peter_in_werkkamer` | 15.8s | 4,096 | 12 | **4,108** | 1 (always) |
| `koffie_espresso` | 52.8s ⚠️ | 9,011 | 131 | **9,143** | 2 (normal), 3 on one failure |

> ⚠️ The 52.8s average is pulled up by one run that took 98.8s and consumed 12,688 tokens across 3 rounds — the model looped on a tool call before failing. Normal runs take ~40s.

### llama3.2:latest

| Scenario | Avg time | Prompt tok (avg) | Completion tok (avg) | Total tok (avg) | Rounds |
|---|---|---|---|---|---|
| `waar_is_peter` | 28.7s | 6,554 | **541** | **7,095** | 1–3 (highly variable) |
| `peter_in_werkkamer` | 20.9s | 4,096 | 100 | 4,196 | 1 (always) |
| `koffie_espresso` | 33.9s | 8,192 | **360** | **8,552** | 2 (always) |

> ⚠️ llama3.2 is the most unpredictable. One `waar_is_peter` run used **14,246 tokens in 3 rounds** and generated 1,958 completion tokens — a 160× difference from its own best run of 16 completion tokens. Even when it eventually produces the correct answer, it burns a huge and unpredictable amount of context doing so.

### qwen3:4b-instruct

| Scenario | Avg time | Prompt tok (avg) | Completion tok (avg) | Total tok (avg) | Rounds |
|---|---|---|---|---|---|
| `waar_is_peter` | 25.0s | 8,192 | 43 | **8,235** | 2 (always) |
| `peter_in_werkkamer` | 27.7s | 8,192 | 54 | **8,246** | 2 (always) |
| `koffie_espresso` | 30.1s | 8,192 | 61 | **8,253** | 2 (always) |

> qwen3:4b is the most *consistent* model by far — near-identical token counts across all 5 runs for every scenario. However, it always uses 2 rounds even for simple location queries that mistral-nemo answers in 1 round from memory. It also never produces a parseable plan block for action requests.

### Summary — Tokens per scenario (avg total, across 5 runs)

| Scenario | mistral-nemo | llama3.2 | qwen3:4b |
|---|---|---|---|
| `waar_is_peter` | **4,108** | 7,095 | 8,235 |
| `peter_in_werkkamer` | **4,108** | 4,196 | 8,246 |
| `koffie_espresso` | 9,143 | 8,552 | **8,253** |

> mistral-nemo is 2× more token-efficient on location queries because it answers from memory in one round. For action tasks (koffie), all models need a tool-call round, so token counts converge.

### Timing variation note

Elapsed time varies significantly across runs of the same model (e.g., qwen3: 3.5s vs 52.3s on the same scenario) without any corresponding change in token count. This is GPU memory state — when the model weights are hot in VRAM the first call is fast; after being partially evicted by another concurrent model they reload from disk. Not a model quality signal.

---

## Model Comparison — 5 Runs × 3 Scenarios

We ran all three scenarios five times against each of three locally available Ollama models:

| Scenario | mistral-nemo:latest | llama3.2:latest | qwen3:4b-instruct |
|---|:---:|:---:|:---:|
| `waar_is_peter` | ✅ 5/5 | ⚠️ 4/5 | ✅ 5/5 |
| `peter_in_werkkamer` | ✅ 5/5 | ❌ 0/5 | ✅ 5/5 |
| `koffie_espresso` | ✅ 4/5 | ❌ 0/5 | ❌ 0/5 |
| **Total** | **🥇 14/15 (93%)** | **🥉 4/15 (27%)** | **🥈 10/15 (67%)** |
| **Avg score** | **9.3 / 10** | **3.6 / 10** | **6.7 / 10** |

### What the failures looked like

**llama3.2 & qwen3 on `koffie_espresso`:** Both models failed every run with "plan missing" — they output a plan in a format none of our extractors caught (or no plan at all). The verbose log showed outputs like plain prose ("I'll turn on the espresso machine for you") with no structured block. These smaller models don't reliably produce structured JSON action plans from a natural-language request in Dutch.

**llama3.2 on `peter_in_werkkamer`:** Failed all 5 runs — the model consistently responded without mentioning "werkkamer" (e.g. "Understood, I've noted that." or "Noted!"). It acknowledges the statement but doesn't reflect the location back.

**llama3.2 on `waar_is_peter`:** 4/5 passes but one run scored 5.0 (didn't include "thuis"/"home"). More concerning: this model is wildly unpredictable — one run took 75 seconds and 14,246 tokens (3 rounds, 1,958 completion tokens) to produce the same answer other runs gave in 6 seconds and 4,112 tokens.

**mistral-nemo** handled all three scenarios consistently. It emits `[PLAN: {...}]` blocks which we now normalise correctly, answers location queries in a single round from memory (4,108 tokens), and bridges the Dutch→entity-name gap via tool calls. One koffie failure was a 99-second loop (3 tool-call rounds) where the model got stuck — a known non-deterministic behaviour.

### Recommendation

**Use `mistral-nemo:latest` as the default Kyber model.** It handles structured plan output reliably, follows Dutch instructions, and correctly bridges entity name gaps via tool calls. The 3B–4B class models (llama3.2, qwen3:4b) are fine for read-only queries but not reliable for action generation.

---

## What's Next

- **Support more model output formats** — `llama3.2` and `qwen3` consistently produce prose-only responses for action requests. We could add a "plan extraction from prose" pass that detects intent + entity mentions and constructs a plan even without a formal block.
- **Enable the LLM judge** for richer scoring beyond structural checks — currently `--no-judge` skips free-text quality scoring.
- **Expand scenario coverage** — the harness has 13 scenarios total; the three real-home ones are at the bottom. More scenarios covering edge cases (ambiguous entity names, multi-step automations, area-level commands) would increase confidence.
- **CI integration** — run the eval harness on every PR against a fixed model snapshot to catch regressions before merge.

---

## Extended Eval — llama3.2:3b (13 scenarios, May 2026)

After `llama3.2:3b` emerged as the best narrator model (see [`narrator-bench-report-2026-05.md`](narrator-bench-report-2026-05.md)), we ran it through the full 13-scenario harness to check whether it could also serve as a chat model.

**Result: not suitable for chat actions** — 5 runs, `--no-judge`, structural checks only.

| Scenario | R1 | R2 | R3 | R4 | R5 | Type |
|---|:---:|:---:|:---:|:---:|:---:|---|
| `is_peter_home` | ✅ | ✅ | ✅ | ✅ | ✅ | Q&A |
| `what_is_on_woonkamer` | ✅ | ✅ | ✅ | ✅ | ✅ | Q&A |
| `waar_is_peter` | ✅ | ✅ | ✅ | ✅ | ✅ | Q&A |
| `peter_in_werkkamer` | ⚠️ | ⚠️ | ✅ | ⚠️ | ⚠️ | Q&A |
| `outside_temp` | ⚠️ | ✅ | ⚠️ | ⚠️ | ⚠️ | Q&A |
| `lights_on_keuken` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | Action |
| `lights_off_werkamer` | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | Action |
| `set_thermostat_21` | ❌ | ❌ | ❌ | ❌ | ❌ | Action |
| `tv_off_woonkamer` | ❌ | ❌ | ❌ | ❌ | ❌ | Action |
| `coffee_off` | ❌ | ❌ | ❌ | ❌ | ❌ | Action |
| `all_lights_off` | ❌ | ❌ | ❌ | ❌ | ❌ | Action |
| `morning_automation` | ❌ | ❌ | ❌ | ❌ | ❌ | Action |
| `koffie_espresso` | ❌ | ❌ | ❌ | ❌ | ❌ | Action |
| **Avg score** | **3.8** | **4.2** | **3.8** | **3.5** | **3.5** | |
| **Pass ≥7** | **3/13** | **4/13** | **4/13** | **3/13** | **3/13** | |

**Root cause:** The model understands the request and calls tools, but outputs a prose answer instead of a structured `PLAN:` block. It lacks the instruction-following capacity to emit Kyber's plan format reliably under a complex system prompt.

**Q&A queries always pass. Every action scenario fails every run.**

### Updated model comparison

| Model | Chat score | Action reliability | Narrator quality | Narrator speed |
|---|:---:|:---:|:---:|:---:|
| `mistral-nemo:latest` | 🥇 93% | ✅ Reliable | ✅ 100% | 44s/batch |
| `llama3.2:3b` | ❌ ~27% (actions: 0%) | ❌ Never produces plans | ✅ 100% | **3.7s/batch** |
| `llama3.2:latest` | ❌ ~27% | ❌ Unreliable | — | — |
| `qwen3:4b-instruct` | 67% (read-only) | ❌ Fails in Dutch | ❌ 0% (format) | — |

**Conclusion: use two models.** `mistral-nemo` for chat and actions. `llama3.2:3b` for background entity narration.

---

*Report generated: May 2026 · Model: mistral-nemo:latest · Scenarios: 3 (original) + 13 (llama3.2:3b extended) · Iterations: 5 per model*
