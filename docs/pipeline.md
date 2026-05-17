# Kyber request pipeline

This document explains, end-to-end, what happens between the moment the user
hits **Send** in the chat panel and the moment the assistant reply is rendered.
It covers the four big additions of v0.1.30 / v0.1.31:

- Knowledge-store *embeddings* (TF-IDF hybrid retrieval).
- Per-turn *debug bundle* (downloadable zip per assistant reply).
- The separate **Kyber Debug** sidebar entry.
- The runtime *debug-mode* flag that hides UI gimmicks for end users.

```
┌──────────┐    ┌──────────────────┐    ┌────────────────────────┐    ┌────────────┐
│ Frontend │ →  │ KyberView.post   │ →  │ AI Task entity (Ollama)│ →  │ Frontend   │
│ panel    │    │ (http_api.py)    │    │ via HA AITaskFeature   │    │ render     │
└──────────┘    └──────────────────┘    └────────────────────────┘    └────────────┘
                       │                                                    ▲
                       ├── live progress events ────────────────────────────┤
                       └── per-turn snapshot ───────────────► Debug panel ──┘
                                                                Debug zip
```

## 1. Request enters the backend

Endpoint: `POST /api/kyber/complete` → `KyberView.post()` in `http_api.py`.

The request body carries:

| field               | meaning                                                          |
| ------------------- | ---------------------------------------------------------------- |
| `prompt`            | the raw user message                                             |
| `history`           | recent user/assistant messages (kept short, rolling window)      |
| `compacted_summary` | optional long-history summary built by `KyberSummarizeView`      |
| `editor_mode`       | which surface is open: `automation` / `script` / `dashboard`     |
| `request_id`        | client-supplied id (server-generated if missing)                 |
| `dashboards`        | dashboard list + URLs from the frontend                          |

`request_id` is the spine of the pipeline: it's used for live progress
streaming, for the per-turn debug snapshot, and for the downloadable bundle.

## 2. Per-turn telemetry attaches early

As soon as `request_id` is known we:

1. Attach `_KyberTurnLogHandler` to the root logger — it captures any record
   whose logger name starts with `kyber` or `custom_components.kyber`. Records
   are appended to an in-memory list bound to this turn only. The handler is
   detached in the `finally` of the snapshot capture block, regardless of
   what happens between.

2. Start a wall-clock timer (`_turn_started_at`).

3. Begin emitting **progress events** via `_progress_emit(hass, request_id, …)`.
   These are polled by the frontend's `KyberProgressView` and used to drive
   the "Reasoning over results…" card.

## 3. Context build

`_build_context(hass)` collects everything the model needs to know about the
home: areas, labels, automations, scripts, an entity *count* per domain
(never the full id list), and the current entity state grouped by area.

The result is two things:

- `context` — a rendered Markdown blob inserted into the system prompt.
- `context_stats` — `{entity_count, area_count}` for the UI badge.

We also build a `dash_lines` block from `dashboards` so the model can name a
real `url_path` when emitting Lovelace YAML.

## 4. Knowledge / memory retrieval (hybrid embeddings + keywords)

`get_knowledge_store(hass)` returns the singleton `KnowledgeStore`. It
backs onto HA `Store` for persistence but keeps two **in-memory indexes**:

- A **TF-IDF vector** per entry built over `subject ⊕ content ⊕ tags ⊕ category`,
  using lowercase word unigrams **plus** word bigrams. IDF is recomputed
  lazily whenever an entry mutates (`_index_dirty = True`).
- The legacy **substring + token-overlap** scorer, still used as one input
  to the hybrid.

When a turn starts we call `async_pick_relevant(prompt, max_entries=8)`:

```text
semantic ← async_semantic_search(prompt, limit=16)   # cosine over TF-IDF
keyword  ← async_search(prompt, limit=16)            # substring + overlap
merge:
    score_for_id = max(semantic_score, 0.3 if keyword_hit else 0)
                 + 0.05 bonus if both hit
return top-8 by merged score
fallback: high-confidence `area_alias` entries if nothing scored
```

Every entry returned carries:

- `_score` — final blended score (used by the UI's chip + the snapshot).
- `_source` — `"semantic"`, `"keyword"`, `"hybrid"`, or `"fallback_alias"`.

The chosen entries are:

- Appended to the system prompt under a **Learned knowledge** section that
  shows the score and source per fact, so the model can decide how much
  weight to give it.
- Emitted as a `progress_emit("info", "Recalled N memory fact(s): …")` so
  the user sees in real time which facts were considered.
- Logged at INFO level (`Kyber: injected N memory facts via hybrid …`) so
  they appear in `logs.txt` of the debug bundle.
- `hits` counter bumped via `async_record_hit`.

## 5. Tool-calling loop

The instructions block, plus the `[TOOL_CALL: …]` tool schema, plus the
context + knowledge sections, are sent to the configured AI Task entity.
The model can respond with either:

- A normal markdown reply (terminates the loop), or
- One or more `[TOOL_CALL: {...}]` directives (single-line JSON).

For each tool call we execute the tool synchronously, append a `tool_result`
block back into the instructions, increment the round counter and re-ask
the model. This continues until either the model replies in prose or
`_TOOL_CALL_MAX_ROUNDS` is hit.

Each tool call adds an entry to `tool_log` with `name`, `args`, `status`,
`ms`, and a small result preview.

## 6. Response cleanup

Models still sometimes leak narration or role-played tool calls. The
cleanup stage (added in v0.1.28) runs in order:

1. `_strip_role_echo_prefix` — drops a leading `User: … / Assistant: …` echo.
2. `_rewrap_bare_action_fences` — merges loose action JSON blocks into a
   single ```plan``` block (handles `{action…}`, `[{…},{…}]`, and `{"actions":[…]}`).
3. `_BARE_JSON_TOOL_RESULT_RE` — strips standalone JSON tool-result lines.
4. `_NARRATION_PATTERNS` — scrubs lines like "I'll call X", "Based on the
   result, I propose…", "Please let me know if this is acceptable.".
5. `_augment_brightness_intent` — adds `brightness_pct:100` for max/full and
   `brightness_pct:10` for dim when missing.

## 7. Auto-rating

If the cleaned response still contains negative cues ("I don't know",
"couldn't find", "no matching entities"…), the knowledge entries used in
this turn get `user_rating = 2` and `needs_review = true` via the
auto-feedback path. The UI surfaces this with the ⚠ chip on each affected
entry.

## 8. Per-turn snapshot

Before returning, `_debug_record_turn` builds a snapshot containing:

```
request_id, ts, user_prompt,
expanded_prompt, instructions_used,        # both capped at 32 KB
picked_knowledge (with id, score, source, …),
tool_log, intent, response_text (8 KB cap),
auto_rating, elapsed_ms, char_count, approx_tokens,
logs, progress_events, session_meta
```

The snapshot is stored:

- In `hass.data["kyber_debug_last_turn"]` — single slot used by the Status tab.
- In `hass.data["kyber_debug_snapshots"]` — `OrderedDict` keyed by `request_id`,
  capped at 50 entries. Used by the debug-bundle endpoint.
- Tool calls are also fanned out to a 20-entry ring buffer for the Tool
  History view.

All of this is in-memory only and is purged on HA restart.

## 9. Response payload

The handler returns JSON to the frontend:

```jsonc
{
  "response":      "<cleaned text>",
  "yaml_blocks":   [ ... ],
  "plan":          { ... } | null,
  "clarify":       { ... } | null,
  "context_stats": { ... },
  "tool_log":      [ ... ],
  "knowledge_used": ["id1","id2", ...],
  "auto_rating":   2 | null,
  "request_id":    "abc123…"
}
```

## 10. Frontend rendering

`_appendAIResponse(text, yaml_blocks, plan)` renders the bubble. The chat panel
stays clean — no rating widget, no debug-bundle button on individual messages.
Per-turn metadata (`request_id`, `knowledge_used`, `auto_rating`) is stashed on
`this._lastTurnMeta` for the Debug page.

After the response renders, the panel:

1. Refreshes the **Last turn** sub-tab of the **Kyber Debug** sidebar entry if
   the user has it open.

All feedback collection happens in the Debug page (`/kyber-debug`) → *Last
turn* sub-tab, which now shows a prominent "How was this turn?" banner with:

- 👍 / 👎 rating buttons that POST `/api/kyber/knowledge/feedback` for every
  fact recalled this turn,
- a `⬇ download bundle` button that hits
  `GET /api/kyber/debug/bundle?request_id=…`,
- an auto-rating chip (⚠) if the backend flagged the response automatically.

## 11. Debug bundle download

`KyberDebugBundleView.get` builds a fresh zip from the stored snapshot. It
contains:

```
manifest.json         kyber version + ts + intent + elapsed
snapshot.json         everything captured for the turn
user_prompt.txt
expanded_prompt.txt   the full system prompt the model actually saw
instructions_used.txt instructions for the final tool-loop round
response.txt
tool_log.json
knowledge_used.json   each fact with its score + source
progress_events.json
logs.txt              kyber.* log records (human-readable)
logs.json             same, structured
README.txt            an index of the above files
```

The frontend triggers the download via a temporary `<a download>`; the
file is named `kyber-debug-<request_id>-<ts>.zip`.

## 12. Sidebar entries — chat vs. debug

Two `panel_custom` registrations point at the same web component
`kyber-panel`, with different `config.mode`:

- `/kyber` → `mode: "chat"` — normal chat experience.
- `/kyber-debug` → `mode: "debug"` — chat pane is hidden, the debug pane
  fills the page, the close button is hidden. The `🐞` button in the chat
  toolbar simply navigates to `/kyber-debug`.

The web component reads `panel.config.mode` (and falls back to inspecting
`window.location.pathname`) so the same JS bundle drives both routes.

## 13. Debug-mode flag

`GET /api/kyber/debug/mode` and `POST /api/kyber/debug/mode {enabled}`
read/write `hass.data["kyber_debug_mode"]`. Default is **on**, which means
all debug affordances (the 🐞 button, per-message `⬇ debug` button) are
visible. Turning it off hides them in the UI but the backend still records
snapshots cheaply — flip the flag back on and the next turn's bundle is
already there to download.

This flag is the user-facing kill-switch for the developer ergonomics. The
sidebar entry **Kyber Debug** itself is always registered (admins-only),
but it only becomes useful when there is at least one captured turn.
