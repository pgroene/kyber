# Kyber Prompt Eval Harness

Offline eval loop that runs test scenarios against a **local Ollama model** — no live HA needed.
Each run scores the model, identifies failures, and asks the LLM to propose a prompt fix.
After N iterations you see a score-per-scenario-per-run table.

---

## Quick start

```bash
# 5 iterations, LLM judge on (default)
python scripts/prompt_eval.py --model qwen3:4b-instruct

# Faster: skip LLM judge, structural checks only
python scripts/prompt_eval.py --model qwen3:4b-instruct --no-judge

# Write best prompt back to const.py when done
python scripts/prompt_eval.py --model qwen3:4b-instruct --save-prompt
```

Prerequisites: [Ollama](https://ollama.com) running locally with your model pulled:
```bash
ollama pull qwen3:4b-instruct
```

---

## Getting real home data

The harness ships with a **simulated** home. To run against your real home:

### 1. Export from Kyber debug panel

1. Open Home Assistant → `/kyber-debug` → **Status** tab
2. Click **📥 Home state** → saves `kyber-home-state-<timestamp>.json`
3. Click **🧠 Memory export** → saves `kyber-memory-<timestamp>.json`

> **⚠️ These files contain your real entity IDs, states, and learned facts.**
> **Never commit them.** They are blocked by `.gitignore`.

### 2. Load data into the harness

Place the files in `scripts/data/` (also gitignored):

```
scripts/data/
  kyber-home-state-latest.json
  kyber-memory-latest.json
```

Then run with `--home-state` and `--memory`:

```bash
python scripts/prompt_eval.py \
  --model qwen3:4b-instruct \
  --home-state scripts/data/kyber-home-state-latest.json \
  --memory     scripts/data/kyber-memory-latest.json
```

When these flags are provided the harness replaces the built-in simulated home
with your real entity list, areas, and knowledge facts.

---

## Test scenarios

Scenarios live in `scripts/prompt_eval.py` → `TEST_SCENARIOS`. Each has:

| Field | Description |
|---|---|
| `id` | Unique slug shown in score table |
| `user` | The message the user sends (Dutch natural language) |
| `description` | What a correct response looks like |
| `expect_type` | `"action"` (plan block required) or `"chat"` (text only) |
| `checks` | List of structural assertions (see below) |

### Check types

| Check | Passes when |
|---|---|
| `("tool_called", "name")` | model called this tool at any point |
| `("plan_service", "dom.svc")` | plan block contains this service |
| `("plan_exists",)` | any plan block was produced |
| `("plan_contains_value", "x")` | plan JSON contains this string |
| `("no_plan",)` | chat response, no plan block |
| `("response_contains", "x")` | final response text contains substring |
| `("response_contains_one_of", [...])` | final response contains any of the strings |
| `("state_read", "entity_id")` | `get_entity_state` was called for this entity |

### Current scenarios

| ID | Prompt | What it tests |
|---|---|---|
| `lights_off_werkamer` | Doe de lichten in de werkamer uit | Uses `get_area_entities`, never guesses IDs |
| `outside_temp` | Hoe warm is het buiten? | Chat answer, no plan, reads sensor |
| `set_thermostat_21` | Zet de verwarming op 21 graden | `climate.set_temperature` plan |
| `is_peter_home` | Is Peter thuis? | Presence check, chat answer |
| `lights_on_keuken` | Zet de keuken lampen aan | `get_area_entities` + `light.turn_on` |
| `tv_off_woonkamer` | Zet de televisie in de woonkamer uit | `media_player.turn_off` plan |
| `what_is_on_woonkamer` | Wat staat er aan in de woonkamer? | Tool call + chat, no plan |
| `coffee_off` | Zet het koffiezetapparaat uit | `switch.turn_off` plan |
| `all_lights_off` | Doe alle lichten in huis uit | Plan with `turn_off` |
| `morning_automation` | Maak een automatisering… | Plan block exists |
| `waar_is_peter` | Waar is Peter? | `person.peter=home`, Dutch, no plan |
| `peter_in_werkkamer` | Waar is Peter precies? | Infers werkkamer from presence sensor |
| `koffie_espresso` | Ik wil koffie | Maps koffie→espresso→correct switch, not lamp/status entity |

---

## Score interpretation

| Score | Meaning |
|---|---|
| 9–10 ✅ | Perfect — all checks pass + LLM judge happy |
| 7–8 ✅ | Good — passes threshold |
| 4–6 ⚠️ | Partial — some checks fail |
| 0–3 ❌ | Wrong — core check failed |

The final score is `0.4 × structural + 0.6 × LLM judge` when judge is on,
or just structural when `--no-judge`.

---

## How the improvement loop works

After each run (except the last), failures are fed to the LLM:

> *"Here are the failing scenarios. What's the root cause?
> Write one new Quick Recipe bullet that would fix the most failures."*

The suggested recipe is prepended to `### Quick recipes` in the system prompt
for the next run. After all iterations the change log shows what was learned.

Use `--save-prompt` to write the final improved prompt back to `const.py`.

---

## What stays in git

| ✅ Committed | ❌ Never committed |
|---|---|
| `scripts/prompt_eval.py` | `scripts/data/*.json` |
| `scripts/run_prompt_tests.py` | `kyber-home-state-*.json` |
| `tests/prompt_regression/cases/*/test.json` | `kyber-memory-*.json` |
| `tests/prompt_regression/cases/*/tool_mocks.json` | Any file with real entity states |
| `tests/prompt_regression/cases/*/memory.json` | |
| `tests/prompt_regression/cases/*/run_history.json` | |
