# Kyber — AI-Powered Smart Home Assistant for Home Assistant

> ⚠️ **ALPHA SOFTWARE — Use at your own risk**
>
> Kyber is in early alpha. Not all features are working and breaking changes may occur between releases.
> **The AI can modify your Home Assistant configuration** — automations, scripts, entities and dashboards.
> Always review proposals before executing them.
> **Make a full backup of your Home Assistant instance before installing or experimenting with Kyber.**

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Kyber is a local AI chat panel for Home Assistant, powered by your **Ollama** instance. Chat with your smart home, manage entities, edit automations, and build dashboards — all without leaving HA.

## Install via HACS

1. In HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/pgroene/kyber` as an **Integration**
3. Find **Kyber** in the HACS store and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search for **Kyber**

Or use the quick-add button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pgroene&repository=kyber&category=integration)

## Features

- 💬 **AI Chat** — ask questions and give commands in natural language; automatic language detection with locale-specific vocabulary hints (Dutch supported out of the box)
- 📋 **Proposal Cards** — review changes before they're applied, with one-click Undo
- ⚡ **Autopilot Mode** — auto-execute proposals for hands-free operation
- ✏️ **Automation & Script Editor** — CodeMirror 6 YAML editor with AI assistance
- 📊 **Dashboard Editor** — edit Lovelace dashboards as YAML, create new dashboards
- 🔧 **Slash Commands** — `/dashboard`, `/automation`, `/script`, `/blueprint`, `/area`
- 🔒 **100% Local** — all AI inference runs on your own Ollama instance; nothing leaves your network
- 🔌 **Integration Explorer** — on startup Kyber automatically indexes every loaded HA integration: sensor names, entity IDs (including groups, template sensors, input helpers, utility meters), and natural-language capability descriptions. Stored as searchable knowledge facts so the AI can answer "what is my solar yield?" without you having to say "goodwe"
- 🔬 **Deep Analyzer** — on-demand AI extraction of durable home facts from automations / scripts / blueprints across **8 analytical lenses**: daily routines, device inventory, occupancy patterns, time/location triggers, energy usage, safety rules, entity relationships & dependencies, and automation purpose & use case
- 🧠 **Hybrid memory retrieval** — knowledge entries are indexed with an in-memory TF-IDF embedding; each turn picks the top facts via cosine similarity blended with keyword overlap. Selected facts are streamed to the live progress card so you can see what Kyber recalled. See [docs/pipeline.md](docs/pipeline.md) for the full request lifecycle
- 🔁 **Tool-calling loop** — up to 5 rounds of tool calls per turn; duplicate call detection with targeted redirect hints prevents the AI from looping. Tool name aliases resolve common model typos/variants automatically
- 🗂️ **Conversation sessions** — named sessions with full rolling history and automatic compaction via summarization
- 🐞 **Kyber Debug panel** — a dedicated second sidebar entry (`/kyber-debug`) with five tabs: **Memory** (browse/rate/refine all knowledge), **Last turn** (full system prompt, tool log, knowledge used, one-click debug bundle), **Status** (entity explorer + narrator progress, download debug bundle), **📋 Logs** (live ring buffer of the last 2,000 Kyber log records with level filter + download), and **Tests**
- 📦 **Debug bundle download** — every assistant turn has a downloadable ZIP with the user prompt, the full expanded system prompt the model actually saw, picked memory entries, tool log, progress events, captured `kyber.*` logs and the response — perfect for filing a precise issue

## Quick Start

See **[docs/installation.md](docs/installation.md)** for full setup instructions.

**Requirements:** Home Assistant 2025.2+, Ollama with a model pulled, HA Ollama integration configured.

```bash
# Docker dev setup
docker compose -f docker-compose.dev.yml up
# then open http://localhost:8123
```

After install, Kyber registers **two sidebar panels**:

| Panel | URL | Purpose |
|---|---|---|
| **Kyber** | `/kyber` | Main chat interface |
| **Kyber Debug** | `/kyber-debug` | Memory browser, last turn details, entity narrator progress, live logs |

## Choosing a Model

Kyber requires an **Ollama** model configured through the HA Ollama integration. Not all models perform equally — smaller models often fail to produce the structured plan blocks Kyber needs for action requests.

Based on the [May 2026 eval report](docs/eval-report-2026-05.md) (5 runs × 3 real-home scenarios):

| Model | Score | Notes |
|---|:---:|---|
| `mistral-nemo:latest` | 🥇 14/15 (93%) | Recommended — reliable plan output, handles Dutch, 1-round answers from memory |
| `qwen2.5:latest` | ✅ check | Not yet in the formal eval; community reports suggest strong structured output — worth trying if mistral-nemo is too slow on your hardware |
| `qwen3:4b-instruct` | 🥈 10/15 (67%) | Good for read-only queries; fails action plans in Dutch |
| `llama3.2:latest` | 🥉 4/15 (27%) | Unpredictable token usage; often skips plan blocks entirely |

**Recommendation: use `mistral-nemo:latest`.** It reliably emits structured plan blocks, bridges Dutch entity name gaps via tool calls, and answers location queries in a single round. 3B–4B class models work for questions but are not reliable for executing actions.

See [docs/eval-report-2026-05.md](docs/eval-report-2026-05.md) for full methodology, timing data, and failure analysis.

### Entity Narrator Model

The background **entity narrator** uses a separate model call that only needs to produce short structured aliases — not full plan blocks. A smaller, faster model is ideal here.

Based on the [May 2026 narrator bench](docs/narrator-bench-report-2026-05.md) (19 models, batch sizes 1 and 10, warmup-corrected):

| Model | Quality@10 | Batch 10 time | Notes |
|---|:---:|---:|---|
| `llama3.2:3b` | ✅ 100% | **3.7s** | 🏆 Recommended — 12× faster than mistral-nemo, 1.9 GB |
| `phi3:mini` | ✅ 95% | 9.1s | Strong backup — slightly larger at 2.3 GB |
| `llama3:latest` | ✅ 100% | 11.0s | Reliable but slower |
| `mistral-nemo:latest` | ✅ 100% | 44.0s | Former recommendation — still works, just slow for narration |
| `qwen3:*`, `deepseek-r1:7b` | ❌ 0% | — | Reasoning/thinking models — format not compatible |

**Recommendation: use `llama3.2:3b` for narration.** See [docs/narrator-bench-report-2026-05.md](docs/narrator-bench-report-2026-05.md) for the full breakdown.

| Doc | Contents |
|---|---|
| [docs/installation.md](docs/installation.md) | Prerequisites, manual install, Docker dev setup, version bumping, tests |
| [docs/chat-and-ai.md](docs/chat-and-ai.md) | Chat basics, proposal cards, autopilot, conversation history, entity autocomplete |
| [docs/slash-commands.md](docs/slash-commands.md) | All slash commands: `/dashboard`, `/automation`, `/script`, `/blueprint`, `/area` |
| [docs/editor.md](docs/editor.md) | Automation/script editor, dashboard editor, Lovelace card type reference |
| [docs/pipeline.md](docs/pipeline.md) | End-to-end request pipeline — context build, hybrid memory retrieval (TF-IDF embeddings), tool loop, response cleanup, per-turn snapshot, debug bundle, debug-mode flag |
| [docs/architecture.md](docs/architecture.md) | Frontend, backend endpoints, context building, plan/action system |
| [docs/eval-report-2026-05.md](docs/eval-report-2026-05.md) | 📊 **May 2026 eval report** — building the real-home prompt eval harness, what we fixed, and model comparison (mistral-nemo vs llama3.2 vs qwen3) |
| [docs/narrator-bench-report-2026-05.md](docs/narrator-bench-report-2026-05.md) | 📊 **May 2026 narrator bench** — 19 small models tested for entity narration quality and speed; `llama3.2:3b` wins (12× faster than mistral-nemo, same quality) |

## Architecture at a Glance

| Layer | Technology |
|---|---|
| AI provider | HA Ollama integration via `ai_task.async_generate_data()` (HA 2025.2+) |
| Backend | Modular Python custom component — 14+ modules covering context building, tool execution, knowledge store, session management, debug diagnostics, integration explorer, and deep analysis |
| Frontend | Shadow DOM web component with CodeMirror 6 YAML editor |

### Backend modules

| Module | Responsibility |
|---|---|
| `http_api.py` | Main AI request handler — prompt assembly, tool-call loop, intent classification, mode rules |
| `action_execution.py` | Plan action executor — service calls, area/label assignments, undo tracking |
| `knowledge.py` | TF-IDF knowledge store — add, search, rate, purge facts |
| `knowledge_integration.py` | Knowledge HTTP views — CRUD, shallow & deep analyze, feedback, purge |
| `integration_explorer.py` | Startup integration indexer — sensors, entity IDs, capability facts for all platforms |
| `deep_analyzer.py` | AI-powered automation/script/blueprint fact extractor (8 analytical lenses) |
| `session_and_storage.py` | Chat session management — multi-session store, history, summarization |
| `debug_and_diagnostics.py` | Per-turn debug snapshots, bundle ZIP builder, bug report, debug-mode flag |
| `intent_and_context.py` | Intent classification, quick-intents, home-state context builder |
| `tool_execution.py` | Tool handler dispatch, alias resolution, domain priority ranking |
| `language_hints.py` | Language detection and locale-specific vocabulary hints (Dutch + extensible) |
| `domain_docs.py` | Per-domain documentation injected into tool context |
| `response_processing.py` | Response cleanup — strip tool echoes, narration, rewrap action blocks |
| `source.py` | Raw YAML readers for automations, scripts, blueprints + content-hash memos |

### API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/kyber/complete` | Prompt + history + HA context → AI response + plan |
| `POST /api/kyber/execute` | Execute plan actions (service calls, area/label/entity management) |
| `POST /api/kyber/parse_yaml` | YAML string → JSON config (used before saving via HA API) |
| `POST /api/kyber/summarize` | Compact conversation history into a summary |
| `GET /api/kyber/progress` | Live progress events (polled by the frontend during AI turns) |
| `GET /api/kyber/history` | Retrieve chat history for the active session |
| `GET /api/kyber/sessions` | List all named sessions |
| `POST /api/kyber/sessions/name` | Rename a session |
| `GET /api/kyber/knowledge` | List knowledge store entries |
| `POST /api/kyber/knowledge` | Add or update a knowledge entry |
| `POST /api/kyber/knowledge/analyze` | Shallow automation analysis → knowledge facts |
| `POST /api/kyber/knowledge/analyze_deep` | Deep AI-driven analysis across all 8 lenses |
| `POST /api/kyber/knowledge/feedback` | Rate knowledge entries (👍/👎) |
| `POST /api/kyber/knowledge/purge` | Delete knowledge entries by filter |
| `GET /api/kyber/debug/last_turn` | Last-turn debug snapshot (system prompt, tool log, knowledge used) |
| `GET /api/kyber/debug/tool_history` | Ring buffer of recent tool calls |
| `GET /api/kyber/debug/status` | Integration status + entity/area counts |
| `GET /api/kyber/debug/bundle` | Download per-turn debug ZIP by `request_id` |
| `GET /api/kyber/debug/bug-report` | Download sanitised bug report ZIP |
| `GET/POST /api/kyber/debug/mode` | Read or toggle debug-mode flag |

## License

MIT — see [LICENSE](LICENSE)
