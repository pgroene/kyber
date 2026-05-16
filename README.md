# Kyber — AI-Powered Smart Home Assistant for Home Assistant

Kyber is a local AI chat panel for Home Assistant, powered by your **Ollama** instance. Chat with your smart home, manage entities, edit automations, and build dashboards — all without leaving HA.

## Features

- 💬 **AI Chat** — ask questions and give commands in natural language (multilingual, fuzzy matching)
- 📋 **Proposal Cards** — review changes before they're applied, with one-click Undo
- ⚡ **Autopilot Mode** — auto-execute proposals for hands-free operation
- ✏️ **Automation & Script Editor** — CodeMirror 6 YAML editor with AI assistance
- 📊 **Dashboard Editor** — edit Lovelace dashboards as YAML, create new dashboards
- 🔧 **Slash Commands** — `/dashboard`, `/automation`, `/script`, `/blueprint`, `/area`
- 🔒 **100% Local** — all AI inference runs on your own Ollama instance

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

MIT
