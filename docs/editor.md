# Kyber YAML Editor

Kyber embeds a full-featured YAML editor directly in the Home Assistant sidebar panel. It supports editing **automations**, **scripts**, and **Lovelace dashboards** — all without leaving the chat interface.

---

## Automation / Script Editor

### Opening the editor

The automation/script editor can be opened in three ways:

1. **AI proposal** — when you ask the AI to edit an automation or script, it returns a `plan` block. Click **Open YAML editor** to load the file:

   ```plan
   {
     "open_editor": true,
     "automation_id": "automation.morning_lights",
     "summary": "Add a sunrise trigger to the morning lights automation"
   }
   ```

2. **Slash command** — type directly in the chat input:

   ```
   /automation open morning lights
   /script open bedtime scene
   ```

   Kyber performs a fuzzy match on the name and shows a confirmation card before opening.

3. **`/automation new`** — opens Home Assistant's native automation editor in a new browser tab.

### CodeMirror 6 editor features

The embedded editor is powered by [CodeMirror 6](https://codemirror.net/) and includes:

| Feature | Details |
|---|---|
| YAML syntax highlighting | Full tokenisation of keys, values, strings, and anchors |
| Line numbers | Displayed in the left gutter |
| Bracket matching | Highlights matching `{`, `[`, and `"` pairs |
| Fold gutters | Collapse/expand nested YAML blocks |
| Autocomplete | Context-aware suggestions |
| One-dark theme | Easy-on-the-eyes dark colour scheme |
| Keyboard shortcut isolation | HA's global shortcuts are suppressed while typing |

### Saving

1. Edit the YAML in the editor.
2. Click the **Save** button (enabled as soon as you make a change).
3. Kyber POSTs the raw YAML to `/api/kyber/parse_yaml` for server-side parsing into JSON.
4. The resulting JSON config is written back to HA via the config REST API:

   | Kind | API path |
   |---|---|
   | Automation | `config/automation/config/<id>` |
   | Script | `config/script/config/<id>` |

5. On success the status bar shows **Saved ✓** and the change is recorded in the AI chat history so the AI stays aware of what was saved.

### AI context awareness

While the editor is open, the current automation/script YAML is included in every AI request. The AI's suggestions apply directly to the open file — you can ask it to add a trigger, change a condition, or restructure actions and it will return an updated YAML block that can be applied to the editor.

---

## Dashboard Editor

### Opening the editor

The dashboard editor can be opened in two ways:

1. **AI proposal** — when you ask the AI to edit a dashboard, it returns a `plan` block. Click **Open Dashboard Editor** to load the file:

   ```plan
   {
     "open_dashboard": true,
     "url_path": "living-room",
     "summary": "Add a weather card to the living-room dashboard"
   }
   ```

   Use `"url_path": null` (or omit it) for the default **Overview** dashboard.

2. **Slash command**:

   ```
   /dashboard open living-room
   /dashboard open             ← opens Overview (default)
   ```

### Dashboard selector

Once the editor is open a **dropdown selector** appears above the editor. It lists every Lovelace dashboard registered in `hass.panels`. Switching the selection immediately loads that dashboard's YAML without closing the editor.

### Creating a new dashboard

Click the **＋ New dashboard** button (or run `/dashboard new`). You will be prompted for a title. Kyber:

1. Derives a URL slug from the title (e.g. `"My Dashboard"` → `my-dashboard`).
2. Creates the dashboard via the WebSocket API (`lovelace/dashboards/create`) with `mode: storage` and `show_in_sidebar: true`.
3. Adds it to the selector and loads a starter config:

   ```yaml
   title: My Dashboard
   views:
     - title: Home
       cards: []
   ```

### Loading

Dashboard YAML is fetched with:

```
GET /api/lovelace/config?url_path=<url_path>
```

For the default Overview the `url_path` parameter is omitted:

```
GET /api/lovelace/config
```

If no stored config exists for a path (404), the editor pre-populates a blank starter template so you can build from scratch.

### Saving

1. Edit the YAML in the editor.
2. Click **Save dashboard**.
3. The YAML is parsed server-side via `/api/kyber/parse_yaml`.
4. The JSON config is written back via:

   ```
   POST /api/lovelace/config?url_path=<url_path>
   ```

5. The status bar shows: **`<Dashboard name>` saved ✓ — reload the browser tab to see changes**.

> **Note:** Home Assistant caches the Lovelace config in the browser. A hard reload (`Ctrl+Shift+R` / `Cmd+Shift+R`) is required to see changes take effect in the HA UI.

### Additional slash commands

| Command | Action |
|---|---|
| `/dashboard close` | Close the dashboard editor |
| `/dashboard save` | Save the currently open dashboard |
| `/dashboard delete` | Delete the currently open dashboard (shows a danger confirmation card) |

---

## Supported Lovelace Card Types

Kyber's AI is pre-trained on all built-in HA card types. You can reference any of these by name when asking the AI to build or modify a dashboard.

### Device-specific cards

| Type | Key fields |
|---|---|
| `alarm-panel` | `entity: alarm_control_panel.xxx` |
| `light` | `entity: light.xxx` |
| `humidifier` | `entity: humidifier.xxx` |
| `thermostat` | `entity: climate.xxx` |
| `media-control` | `entity: media_player.xxx` |
| `weather-forecast` | `entity: weather.xxx`, `forecast_type: daily\|hourly` |
| `todo-list` | `entity: todo.xxx` |
| `map` | `entities: [person.xxx]`, optional `hours_to_show`, `default_zoom` |
| `calendar` | `entities: [calendar.xxx]` |

### Grouping cards

| Type | Key fields |
|---|---|
| `vertical-stack` | `cards: [...]` |
| `horizontal-stack` | `cards: [...]` |
| `grid` | `cards: [...]`, `columns: 2` |

### Logic cards

| Type | Key fields |
|---|---|
| `conditional` | `conditions: [{entity, state}]`, `card: {...}` |
| `entity-filter` | `entities: [...]`, `conditions: [...]`, `card: {...}` |

### Data display cards

| Type | Key fields |
|---|---|
| `sensor` | `entity: sensor.xxx`, optional `graph: line`, `hours_to_show` |
| `history-graph` | `entities: [sensor.xxx]`, `hours_to_show: 24` |
| `statistics-graph` | `entities: [sensor.xxx]`, `stat_types: [mean,min,max]`, `period: month` |
| `gauge` | `entity: sensor.xxx`, `min: 0`, `max: 100`, `severity: {green: 0, yellow: 50, red: 80}` |
| `markdown` | `content: "## Hello\n{{ states('sensor.xxx') }}"` (Jinja2 supported) |
| `picture` | `image: /local/my-image.jpg`, optional `tap_action` |
| `picture-entity` | `entity: xxx`, `image: /local/my-image.jpg` |
| `picture-glance` | `entities: [xxx]`, `image: /local/bg.jpg` |
| `picture-elements` | Overlay interactive elements on an image |

### Control cards

| Type | Key fields |
|---|---|
| `button` | `entity: switch.xxx`, `tap_action: {action: toggle}` |
| `entity` | `entity: xxx` — shows state + controls |

### Combined display + control cards

| Type | Key fields |
|---|---|
| `tile` | `entity: xxx`, supports `features`; recommended for Sections view |
| `entities` | `entities: [xxx, yyy]`, can include title, dividers, buttons |
| `glance` | `entities: [xxx, yyy]`, compact icon + state grid |
| `area` | `area: living_room` — shows all devices in an area |

### Quick reference: full type list

`alarm-panel` · `button` · `calendar` · `custom` · `entities` · `entity` · `entity-filter` · `gauge` · `glance` · `history-graph` · `humidifier` · `light` · `logbook` · `map` · `markdown` · `media-control` · `picture` · `picture-elements` · `picture-entity` · `picture-glance` · `plant-status` · `sensor` · `shopping-list` · `statistics-graph` · `thermostat` · `tile` · `todo-list` · `weather-forecast` · `webpage`

### Custom HACS cards

On startup, Kyber fetches `/api/lovelace/resources` and scans the registered JavaScript module URLs for `custom:` card type names. These are passed to the AI alongside the built-in list, so the AI can suggest cards like `custom:mushroom-template-card` or `custom:mini-graph-card` when those HACS integrations are installed.

> The AI will always check the custom card list before telling you a card type doesn't exist.

---

## AI-Assisted Editing

### How it works

When the editor is open, Kyber automatically includes the full current YAML in every AI request. The AI is instructed to return the **complete updated YAML** (not just a diff) in a fenced `yaml` block.

Example interaction while the dashboard editor is open:

**You:** Add a weather card for `weather.home` to the first view.

**AI:**
```yaml
title: Home
views:
  - title: Home
    cards:
      - type: weather-forecast
        entity: weather.home
        forecast_type: daily
```

An **Apply to editor** button appears below the YAML block. Click it to replace the editor contents with the suggested YAML.

### Autopilot mode

With **autopilot on** (`/autopilot on`), YAML suggestions from the AI are automatically applied to the editor without requiring manual confirmation. This enables a rapid back-and-forth workflow:

1. Open the dashboard/automation editor.
2. Enable autopilot: `/autopilot on`
3. Describe changes in plain language — the editor updates automatically after each AI response.
4. Click **Save** (or run `/dashboard save`) when you're happy with the result.
