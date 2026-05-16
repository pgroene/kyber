# Kyber — GitHub Copilot Instructions

## Project Overview

Kyber is a **Home Assistant custom integration** providing an AI-powered smart home chat panel. It consists of:

- **`custom_components/kyber/`** — Python HA backend (HTTP API views, context building, AI calls)
- **`www/kyber/kyber-panel.js`** — Frontend web component (single file, Shadow DOM, CodeMirror 6)
- **`www/kyber/codemirror-bundle.js`** — Pre-built CodeMirror 6 bundle (do not edit)
- **`tests/`** — pytest tests using `pytest-homeassistant-custom-component`
- **`docs/`** — Feature documentation

---

## Architecture

- The **frontend** is a single custom element `<kyber-panel>` using Shadow DOM. It communicates with the backend via `fetch` and with Home Assistant directly via `this._hass.callApi()` and `this._hass.callWS()`.
- The **backend** registers HTTP views on HA startup. All views are in `http_api.py`. The AI is called via `ai_task.async_generate_data()` — never call Ollama directly.
- The **AI context** is built in `http_api.py::_build_context()` using HA registries. The system prompt lives in `const.py::SYSTEM_PROMPT_TEMPLATE`.

---

## Key Conventions

### Python (backend)

- All HTTP views extend `HomeAssistantView` from `homeassistant.components.http`
- Use `async/await` throughout — HA is async-first
- Parse request bodies with `await request.json()`
- Return responses with `web.Response(text=..., content_type="application/json")`
- Use `hass.states`, `area_registry`, `entity_registry`, `label_registry` for HA data — never raw DB
- Register all new views in `async_setup_entry` in `__init__.py`
- Keep `const.py` as the single source of truth for the system prompt

### JavaScript (frontend)

- All DOM queries must use `this.shadowRoot.getElementById()` or `this.shadowRoot.querySelector()` — never `document.getElementById()`
- Use `this._hass.callApi("GET"/"POST", "path/without/api/prefix", body?)` for HA REST API calls
- Use `this._hass.callWS({type: "...", ...})` for WebSocket API calls (e.g. creating dashboards)
- Never use `this._hass.auth.data.access_token` + raw `fetch` for HA API calls — use `callApi` instead
- Keep all styles in the `STYLES` template literal at the top of the file
- **Every JS change requires bumping the version** in `__init__.py` (`module_url="/local/kyber/kyber-panel.js?vN"`) and restarting the container

### JS Version Bump Workflow

```
1. Edit kyber-panel.js
2. In __init__.py: increment ?vN → ?v(N+1) in module_url
3. docker restart kyber-ha
4. Hard-refresh browser (Ctrl+Shift+R)
```

Skipping any step causes the browser to serve the old cached JS.

---

## Testing

### Python tests

- Tests use `pytest-homeassistant-custom-component` and `pytest-asyncio`
- Run inside the Docker container: `docker exec kyber-ha sh -c "cd /config && PYTHONPATH=/config pytest tests/ -v"`
- All tests are async (`asyncio_mode = auto` in `pytest.ini`)
- Use `MockConfigEntry` from `pytest_homeassistant_custom_component.common`
- The `setup_integration` fixture in `conftest.py` sets up HTTP + registers views — use it for all HTTP endpoint tests
- Tests run on Linux only (HA constraint) — run in the Docker container on Windows
- Always patch `"custom_components.kyber.http_api.async_generate_data"` — never the old `copilot_assist` path
- Do **not** mock `async_generate_data` to return real Ollama responses in tests — use a simple lambda that returns `_make_ai_result("text")`

#### New Python test files must be copied into the container

The `tests/` directory is **not** live-mounted. After writing a new test file:
```
docker cp tests/test_myfeature.py kyber-ha:/config/tests/test_myfeature.py
```

### JavaScript tests

JS tests use **Vitest + jsdom** and live in `www/kyber/tests/`.

#### Run JS tests

```bash
# In container (required on Windows)
docker exec kyber-ha sh -c "cd /config/www/kyber && npm test"

# Local (if Node.js is installed)
cd www/kyber && npm test
```

If Node.js is not installed in the container:
```bash
docker exec kyber-ha apk add nodejs npm
```

#### Sync new test files to the container

The `www/kyber/` directory **is** live-mounted, but `node_modules/` is inside the container. After writing or editing JS test files:
```bash
docker cp www/kyber/tests/component/my.test.js kyber-ha:/config/www/kyber/tests/component/my.test.js
```

#### JS test structure

```
www/kyber/tests/
  setup.js                      — Imports kyber-panel.js to register custom element
  helpers.js                    — makePanel(), makeUnrenderedPanel(), mockTextarea()
  mocks/codemirror-bundle.js    — No-op stubs for all CodeMirror exports
  unit/
    pure-helpers.test.js        — _escapeHtml, _getTokenAtCursor, _jsonToYaml, _findEntity
    slash-commands.test.js      — _handleSlashCommand routing + sub-command parsing
    autocomplete.test.js        — _onPromptInput dropdown behaviour
  component/
    command-card.test.js        — _buildCommandCard DOM + button behaviour
    plan-card.test.js           — _buildPlanCard rendering, execute, undo, autopilot
    chat-bubbles.test.js        — _appendMessage + _appendAIResponse
  integration/
    ask-ai.test.js              — Full _askAI flow with mocked fetch
    save-automation.test.js     — _saveAutomation parse_yaml + callApi
    compaction.test.js          — _maybeCompact threshold + payload
```

#### Key patterns for JS tests

**`makePanel()` vs `makeUnrenderedPanel()`**
- `makePanel(hassOverrides)` — triggers `_render()`, full Shadow DOM available. Use for component + integration tests.
- `makeUnrenderedPanel(hassOverrides)` — sets `element._hass` directly, no render. Use for pure function tests.

**Initial greeting message**
`makePanel()` causes `_render()` to insert an initial "Hi!" message in `#chat-history`. Tests that count or find `.chat-message.assistant` elements must account for this first message.

**Pre-set `_lovelaceResources` to skip lazy fetch**
`_askAI()` lazily fetches `/api/lovelace/resources` on the first call. In tests, set `element._lovelaceResources = []` and `element._dashboardList = []` before calling to avoid the extra fetch, so `fetch.mock.calls[0]` is always the `/api/kyber/complete` POST.

**`flushPromises()` for async DOM assertions**
```javascript
const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));
card.querySelector(".btn-execute").click();
await flushPromises();
// Now assert DOM state after promise chains resolve
```

**Area rename syntax**
`_cmdArea("rename", nameArg)` splits on `/\s+to\s+/i` — use `"kitchen to Living Kitchen"`, not a space-only separator.

---

## TDD Workflow

**All new functionality must follow this workflow — no exceptions:**

```
1. Docs first       → Write or update the relevant docs/ file describing the feature,
                       its API contract, request/response shape, and edge cases.
2. Tests RED        → Write failing unit tests that assert the documented behaviour.
                       Copy them into the container and verify they fail (not error).
3. Implement GREEN  → Write the implementation until all tests pass.
4. Verify coverage  → Ask: do the tests fully cover what the docs say?
                       Add any missing tests. Update docs if implementation diverged.
5. Repeat           → Until docs ↔ tests ↔ implementation all agree.
```

### Test file conventions

| What you're testing | File name | Key fixture |
|---|---|---|
| HTTP endpoint | `tests/test_<endpoint>.py` | `hass_client`, `setup_integration` |
| Pure helpers (no HA) | `tests/test_helpers.py` | none needed |
| Config flow | `tests/test_config_flow.py` | `hass` (plain) |

### Mock pattern for AI-calling endpoints

```python
_PATCH_GENERATE = "custom_components.kyber.http_api.async_generate_data"

def _make_ai_result(text: str) -> MagicMock:
    r = MagicMock()
    r.data = text
    return r

async def test_something(hass, setup_integration, hass_client):
    captured = {}
    async def fake(hass, *, task_name, entity_id, instructions, **kw):
        captured["instructions"] = instructions
        return _make_ai_result("expected AI output")
    client = await hass_client()
    with patch(_PATCH_GENERATE, side_effect=fake):
        resp = await client.post("/api/kyber/complete", json={"prompt": "test"})
    assert resp.status == 200
    assert "something" in captured["instructions"]
```

### Naming conventions

- Test functions: `test_<thing_being_tested>_<expected_outcome>`
- e.g. `test_invalid_yaml_returns_400`, `test_execute_rename_entity`, `test_missing_prompt_returns_400`

---

## File Map

```
custom_components/kyber/
  __init__.py       — async_setup_entry: registers panel + HTTP views
  config_flow.py    — UI flow: user selects ai_task.* entity
  const.py          — DOMAIN, config keys, SYSTEM_PROMPT_TEMPLATE
  http_api.py       — KyberView (/complete), KyberSaveView (/parse_yaml),
                      KyberExecuteView (/execute), KyberSummarizeView (/summarize)
  manifest.json     — HA integration manifest (dependencies: ollama, ai_task)
  strings.json      — UI strings for config flow

www/kyber/
  kyber-panel.js    — <kyber-panel> web component (~2400 lines, single file)
  codemirror-bundle.js — CodeMirror 6 bundle (DO NOT EDIT)
  package.json      — Vitest + jsdom devDependencies
  vitest.config.js  — JS test runner config (CodeMirror mock, jsdom env)
  tests/            — JS tests (unit/component/integration tiers)

docs/
  installation.md   — Setup, dev loop, version bumping
  chat-and-ai.md    — Chat, proposals, autopilot, context
  slash-commands.md — All /commands reference
  editor.md         — YAML editor, dashboard editor, card types
  architecture.md   — System design, API reference, data flows

tests/
  conftest.py           — Fixtures: mock_config_entry, setup_integration
  test_config_flow.py   — Config flow tests
  test_http_api.py      — /complete and /execute endpoint tests
  test_parse_yaml.py    — /parse_yaml endpoint tests
  test_summarize.py     — /summarize endpoint tests
  test_helpers.py       — Pure unit tests: _extract_yaml_blocks, _extract_plan_block, _build_service_undo
```

---

## Common Patterns

### Adding a new HTTP endpoint

```python
# 1. Create a new view class in http_api.py
class KyberMyView(HomeAssistantView):
    url = "/api/kyber/my_endpoint"
    name = "api:kyber:my_endpoint"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        data = await request.json()
        # ... logic
        return web.Response(
            text=json.dumps({"result": "ok"}),
            content_type="application/json",
        )

# 2. Register it in __init__.py
from .http_api import KyberMyView
hass.http.register_view(KyberMyView())
```

### Adding a new slash command

```javascript
// 1. Add handler in kyber-panel.js
_cmdMyCommand(action, nameArg) {
  switch (action) {
    case "do":
      this._buildCommandCard({
        icon: "🔧", title: "Do something",
        detail: nameArg,
        onConfirm: async (card) => {
          // action
          card.querySelector(".btn-cmd-execute").textContent = "✓ Done";
        },
      });
      break;
    default:
      this._showMsg(`/mycommand commands: do <name>`);
  }
}

// 2. Add to _handleSlashCommand switch
case "mycommand": return this._cmdMyCommand(action, nameArg);

// 3. Add to the routing guard in _askAI
if (["dashboard", "automation", "script", "blueprint", "area", "mycommand"].includes(cmd)) {
```

### Adding a new plan action type (backend)

```python
# In http_api.py KyberExecuteView, add a branch in the action handler:
elif action_type == "my_action":
    # execute against hass
    results.append({"status": "ok", "undo_action": {...}})
```

---

## Do Not

- Do not edit `codemirror-bundle.js` — it is a pre-built artifact
- Do not call Ollama directly — always use `ai_task.async_generate_data()`
- Do not use `document.getElementById()` in the frontend — use `this.shadowRoot`
- Do not use raw `fetch` with manual Bearer tokens for HA API calls — use `this._hass.callApi()`
- Do not add `console.log` debug statements to production code
- Do not create new markdown files for planning — use the session workspace (`~/.copilot/session-state/`)
