# Kyber — Installation & Development Setup

> ⚠️ **ALPHA SOFTWARE — Use at your own risk**
>
> Kyber is in early alpha. Not all features are working and breaking changes may occur between releases.
> **The AI can modify your Home Assistant configuration** — automations, scripts, entities and dashboards.
> Always review proposals before executing them.
> **Make a full backup of your Home Assistant instance before installing or experimenting with Kyber.**

Kyber is a Home Assistant custom integration that adds an AI-powered coding assistant panel to the HA sidebar, backed by a locally running Ollama model.

---

## 1. Install via HACS (Recommended)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/pgroene/kyber` as an **Integration**
3. Find **Kyber** in the HACS store and click **Download**
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search for **Kyber**

Or use the quick-add button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pgroene&repository=kyber&category=integration)

---

## 2. Prerequisites

| Requirement | Notes |
|---|---|
| Home Assistant **2025.1+** | Earlier versions lack the `ai_task` platform |
| [Ollama](https://ollama.com/) running locally | Must be reachable from HA on port `11434` |
| HA **Ollama integration** configured | Settings → Integrations → Ollama |
| At least one **`ai_task.*` entity** | Created automatically by the Ollama integration after setup |

### Verify the ai_task entity

In HA, open **Developer Tools → States** and confirm an entity such as `ai_task.ollama_*` exists before installing Kyber. The config flow will reject an entity ID that cannot be found.

---

## 3. Manual Installation

### Copy integration files

```bash
# From the root of this repository
cp -r custom_components/kyber  /path/to/ha-config/custom_components/kyber
```

> The `www/kyber/` directory is **not needed** for manual installs — frontend files are bundled inside
> `custom_components/kyber/www/` and served automatically by the integration.
>
> **Windows users:** replace `/path/to/ha-config` with the path shown in HA under
> *Settings → System → General → Config directory*.

### Add the integration

1. Restart Home Assistant.
2. Go to **Settings → Integrations → Add Integration** and search for **Kyber**.
3. In the config form:
   - **AI Task Entity ID** — enter the `ai_task.*` entity created by the Ollama integration (e.g. `ai_task.ollama_llama3`). The form auto-populates the first match it finds.
   - **Max Tokens** — maximum tokens per AI response (default 2048, range 256–2,000,000).
4. Click **Submit**. A **Kyber** entry appears in the sidebar.

> Only one Kyber config entry is allowed. To reconfigure, remove the existing entry first.

---

## 4. Local Development (Docker)

`docker-compose.dev.yml` mounts the working-tree directly into the container so that Python changes are picked up on restart without rebuilding an image.

### Start the dev stack

```bash
docker compose -f docker-compose.dev.yml up -d
```

Home Assistant will be available at **http://localhost:8123**.

The Ollama integration must be pointed at `http://host.docker.internal:11434` — the `extra_hosts` entry in `docker-compose.dev.yml` resolves that hostname to the host's gateway automatically.

### Volume layout

| Host path | Container path | Purpose |
|---|---|---|
| `./custom_components` | `/config/custom_components` | Live-mounted integration code |
| `./www` | `/config/www` | Live-mounted frontend assets |
| `ha-config` (named volume) | `/config` | Persistent HA state (DB, users, automations) |

### Dev loop — Python changes

Edit any `.py` file under `custom_components/kyber/`, then restart the container:

```bash
docker restart kyber-ha
```

HA reloads all integrations on start. No browser action is required.

### Dev loop — JavaScript changes

After editing frontend files, sync them to the integration and restart Home Assistant:

1. Edit `www/kyber/kyber-panel.js` (source of truth for dev + tests).
2. Copy to `custom_components/kyber/www/kyber-panel.js` (shipped version).
3. Restart the container: `docker restart kyber-ha`
4. Hard-refresh the browser (`Ctrl+Shift+R` / `Cmd+Shift+R`).

```bash
# Quick sync helper
cp www/kyber/kyber-panel.js custom_components/kyber/www/kyber-panel.js
docker restart kyber-ha
```

## 5. Running Tests

### Python tests

#### Install dependencies

```bash
pip install -r requirements-test.txt
```

This installs `pytest-homeassistant-custom-component` and `pytest-asyncio`.

#### Run the Python test suite

```bash
# Inside the Docker container (required on Windows)
docker exec kyber-ha sh -c "cd /config && PYTHONPATH=/config pytest tests/ -v"

# Or natively on Linux/WSL
pytest tests/ -v --tb=short
```

`pytest.ini` sets `asyncio_mode = auto`, so all `async def test_*` functions are handled without extra decorators.

### JavaScript tests

JS tests use **Vitest + jsdom** and cover the `kyber-panel.js` frontend.

#### First-time setup

Install Node.js in the Docker container (only needed once per container lifetime):

```bash
docker exec kyber-ha apk add nodejs npm
docker exec kyber-ha sh -c "cd /config/www/kyber && npm install"
```

#### Run the JS test suite

```bash
docker exec kyber-ha sh -c "cd /config/www/kyber && npm test"
```

Watch mode (runs tests on file change):

```bash
docker exec kyber-ha sh -c "cd /config/www/kyber && npm run test:watch"
```

#### Sync edited test files to the container

After editing a test file locally, copy it in:

```bash
docker cp www/kyber/tests/component/plan-card.test.js kyber-ha:/config/www/kyber/tests/component/plan-card.test.js
```

> **Note:** Node.js is installed at runtime via `apk add` and is not persisted across container rebuilds. Re-run the first-time setup after `docker compose down && up`.

### GitHub Actions

Tests run automatically on every push to `main` / `dev` and on pull requests targeting `main`:

```
.github/workflows/tests.yml
```

The workflow uses **Python 3.12** on `ubuntu-latest`, installs `requirements-test.txt`, and runs `pytest tests/ -v --tb=short`.

### Windows / WSL workaround (Python)

`pytest-homeassistant-custom-component` depends on several Linux-only HA internals. Running tests natively on Windows will fail. Use one of these approaches:

**Option A — WSL 2 (recommended)**

```bash
# Inside a WSL 2 terminal
cd /mnt/c/workspaces/home-assistant/github-copilot-integration
pip install -r requirements-test.txt
pytest tests/ -v --tb=short
```

**Option B — Docker**

```bash
docker run --rm -it \
  -v "$(pwd):/workspace" \
  -w /workspace \
  python:3.12-slim \
  bash -c "pip install -r requirements-test.txt && pytest tests/ -v --tb=short"
```
