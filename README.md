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

- 💬 **AI Chat** — ask questions and give commands in natural language (multilingual, fuzzy matching)
- 📋 **Proposal Cards** — review changes before they're applied, with one-click Undo
- ⚡ **Autopilot Mode** — auto-execute proposals for hands-free operation
- ✏️ **Automation & Script Editor** — CodeMirror 6 YAML editor with AI assistance
- 📊 **Dashboard Editor** — edit Lovelace dashboards as YAML, create new dashboards
- 🔧 **Slash Commands** — `/dashboard`, `/automation`, `/script`, `/blueprint`, `/area`
- 🔒 **100% Local** — all AI inference runs on your own Ollama instance
- 🐞 **Debug tab** — inspect everything Kyber knows: memory entries, the expanded system prompt of the last turn, which knowledge entries it picked (with similarity scores), tool calls, and per-entry ratings + inline "refine with a hint" action
- 📦 **Debug bundle download** — every assistant message has a `⬇ debug` button (visible on hover) that exports a ZIP with the user prompt, the full expanded system prompt the model actually saw, picked memory entries, tool log, progress events, captured `kyber.*` logs and the response — perfect for filing a precise issue

## Quick Start

See **[docs/installation.md](docs/installation.md)** for full setup instructions.

**Requirements:** Home Assistant 2025.1+, Ollama with a model pulled, HA Ollama integration configured.

```bash
# Docker dev setup
docker compose -f docker-compose.dev.yml up
# then open http://localhost:8123
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/installation.md](docs/installation.md) | Prerequisites, manual install, Docker dev setup, version bumping, tests |
| [docs/chat-and-ai.md](docs/chat-and-ai.md) | Chat basics, proposal cards, autopilot, conversation history, entity autocomplete |
| [docs/slash-commands.md](docs/slash-commands.md) | All slash commands: `/dashboard`, `/automation`, `/script`, `/blueprint`, `/area` |
| [docs/editor.md](docs/editor.md) | Automation/script editor, dashboard editor, Lovelace card type reference |
| [docs/architecture.md](docs/architecture.md) | Frontend, backend endpoints, context building, plan/action system |

## Architecture at a Glance

| Layer | Technology |
|---|---|
| AI provider | HA Ollama integration via `ai_task.async_generate_data()` |
| Backend | Python custom component — context builder, plan executor, YAML parser |
| Frontend | Shadow DOM web component with CodeMirror 6 YAML editor |

### API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/kyber/complete` | Prompt + history + HA context → AI response + plan |
| `POST /api/kyber/execute` | Execute plan actions (entity changes, service calls, area management) |
| `POST /api/kyber/parse_yaml` | YAML string → JSON config (used before saving via HA API) |
| `POST /api/kyber/summarize` | Compact conversation history into a summary |

## License

MIT — see [LICENSE](LICENSE)
