# Kyber — Installation & Development Setup

Kyber is a Home Assistant custom integration that adds an AI-powered coding assistant panel to the HA sidebar, backed by a locally running Ollama model.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Home Assistant **2025.1+** | Earlier versions lack the `ai_task` platform |
| [Ollama](https://ollama.com/) running locally | Must be reachable from HA on port `11434` |
| HA **Ollama integration** configured | Settings → Integrations → Ollama |
| At least one **`ai_task.*` entity** | Created automatically by the Ollama integration after setup |

### Verify the ai_task entity

In HA, open **Developer Tools → States** and confirm an entity such as `ai_task.ollama_*` exists before installing Kyber. The config flow will reject an entity ID that cannot be found.

---

## 2. Manual Installation

### Copy integration files

```bash
# From the root of this repository
cp -r custom_components/kyber  /path/to/ha-config/custom_components/kyber
cp -r www/kyber                /path/to/ha-config/www/kyber
```

> **Windows users:** replace `/path/to/ha-config` with the path shown in HA under
> *Settings → System → General → Config directory*.

### Add the integration

1. Restart Home Assistant.
2. Go to **Settings → Integrations → Add Integration** and search for **Kyber**.
3. In the config form:
   - **AI Task Entity ID** — enter the `ai_task.*` entity created by the Ollama integration (e.g. `ai_task.ollama_llama3`). The form auto-populates the first match it finds.
   - **Max Tokens** — maximum tokens per AI response (default 2048, range 256–8192).
4. Click **Submit**. A **Kyber** entry appears in the sidebar.

> Only one Kyber config entry is allowed. To reconfigure, remove the existing entry first.

---

## 3. Local Development (Docker)

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

The frontend panel is loaded as a versioned static asset. HA (and the browser) aggressively cache it, so **every JS change needs a cache-bust**:

1. Edit the JS file(s) under `www/kyber/`.
2. Bump the `?v=N` query string in `__init__.py` (see [Version Bumping](#4-version-bumping)).
3. Restart the container: `docker restart kyber-ha`
4. Hard-refresh the browser (`Ctrl+Shift+R` / `Cmd+Shift+R`).

---

## 4. Version Bumping

The panel is registered with a versioned URL so that HA and the browser know to fetch a fresh copy:

```python
# custom_components/kyber/__init__.py
module_url="/local/kyber/kyber-panel.js?v=24",
```

**Every time you change a JS file**, increment the version number:

```python
# Before
module_url="/local/kyber/kyber-panel.js?v=24",

# After
module_url="/local/kyber/kyber-panel.js?v=25",
```

Then restart the container and hard-refresh the browser. Skipping the version bump means the old cached file continues to be served even after the file on disk has changed.

---

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
