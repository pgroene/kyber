# Changelog

All notable changes to Kyber are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The `[Unreleased]` section is automatically promoted to a versioned entry by the **Do Release** pipeline on every merge to `main`.

---

## [0.5.7.4] -- 2026-05-22

### Fixed
- Entity IDs in AI response text were not rendered as interactive chips because the system prompt never instructed the AI to wrap them in backticks. Added `### Response formatting` rule: entity IDs in response text must use backtick notation so \\_injectEntityChips\\ can convert them to live-state entity chips with domain icons

---

## [0.5.7.3] — 2026-05-22

### Fixed
- **[Critical]** Bumped all JS mixin import version numbers (?v=N+1) so browsers discard stale cached copies of the mixin files that shipped without _loadActionHistory — the previous hotfix (v0.5.7.2) replaced the files on the server but browsers continued serving old cached versions

---

## [0.5.7.2] — 2026-05-22 â€” 2026-05-22

### Fixed
- **[Critical]** JS frontend files (`utils-mixin.js`, `ai-mixin.js`, etc.) were not being synced to the `www/` mirror, causing `this._loadActionHistory is not a function` on panel load
- `scripts/sync_www.py` now also syncs all JS files (`www/kyber/src/*.js` and `kyber-panel.js`) in addition to Python files, preventing this class of bug in future

---

## [0.5.7.1] â€” 2026-05-22

### Fixed
- **[Critical]** `action_history.py` was missing from the v0.5.7 release, causing Kyber to fail to load in Home Assistant with `ModuleNotFoundError: No module named 'custom_components.kyber.action_history'`

---

## [Unreleased]

## [0.5.8] -- 2026-05-22

### Added
- **Chat history compaction** -- when history exceeds 12 000 chars or 20 messages, oldest context is summarized and replaced with a `-- Older context was summarized --` banner; prevents context-window overflow (#223)
- **Meta field + action history entry ID** -- `[CHANGE]` chat messages now store `history_entry_id` so the Undo button can be restored after a panel reload (#223)
- **Undo button restore on reload** -- chat messages that had an Undo button re-fetch the action history entry on load and re-render a live Undo or greyed Undone button (#223)
- **Action history** -- new `KyberActionHistoryView` + `KyberActionHistoryEntryView` API endpoints; history panel in the UI (#223)
- **Memory improvements** -- equivalence detection (`X and Y are the same`), routine categories, action history integration
- **Release notes inline** -- `/update` and `/update force` now show release notes inline in chat after install instead of just a link (#224)
- **Entity chip adornments** -- AI response text now renders entity IDs as interactive chips with domain icons and live state

### Fixed
- **[Critical]** `action_history.py` missing from v0.5.7 release (v0.5.7.1)
- **[Critical]** JS frontend files not synced to `www/` mirror, causing `_loadActionHistory is not a function` (v0.5.7.2)
- **[Critical]** Browser cache serving stale JS mixin files -- bumped all import version numbers (v0.5.7.3)
- **[Critical]** Entity adornments not showing -- AI never instructed to use backtick notation for entity IDs (v0.5.7.4)
- `sync_www.py` now syncs JS files as well as Python files -- prevents mirror drift

### Added
- **10 new language translations**: DE, FR, ES, IT, PT, PL, HU, SV, RU, ZH-Hans
- **Self-healing execution** â€” when a plan action fails, a correction micro-agent automatically re-tries with domain-specific knowledge; result shown in chat with `[ðŸ”§ CORRECTION]` marker (closes #187)
- Toast notification when a fact is learned from a correction (`_showToast`)
- Approval queue auto-highlights (orange pulse + scroll-into-view) when execution requires approval
- Failed actions now recorded in chat history with `[FAILED]` marker
- i18n: English and Dutch translations for the panel UI via `i18n.js`; all mixin files wired to `this._t`
- `translations/nl.json` â€” Dutch translations for the Home Assistant config flow UI
- `CONTRIBUTING.md` â€” PR-only workflow guide with release checklist
- Playwright tests for copy button behaviour (7 tests) and self-healing correction flow (8 tests)
- `docs/correction-agent.md` â€” architecture guide for the correction micro-agent

### Fixed
- **[Critical]** Chat history race condition â€” each load/save created a new `Store` instance, bypassing per-instance locking. Now a single shared `Store` + `asyncio.Lock` is stored in `hass.data`, preventing concurrent writes from corrupting session data
- **[High]** Path traversal in self-update zip extraction â€” checks for `..` path components and absolute paths _before_ `mkdir()`, preventing writes outside `custom_components/kyber/`
- **[Medium]** Knowledge `_persist()` deadlock â€” split into `_persist()` (acquires lock) and `_persist_unlocked()` (for callers already holding the lock); entry snapshot prevents concurrent mutation
- **[Medium]** XSS in `_appendThinkingEvent` â€” simple events now use `textContent` instead of `innerHTML`; the HTML variant renamed to `_appendThinkingEventHTML` to make its requirements explicit
- Copy button broken on AI messages and in the bug report dialog â€” all 3 clipboard call sites now include an `execCommand('copy')` fallback for HTTP environments
- Pre-existing JS test failures: `_extractSuggestions` cap (6 chips), `_startStatusPolling` timer tests, debug-pane visibility, memory-badge text

---

## [0.5.6] â€” 2026-05-22 01:00 +0200

### Fixed
- **Background AI tasks silently falling back** â€” when the configured AI entity returns "does not support thinking", background tasks now automatically retry via Azure if configured
- **Label creation broken on newer HA** â€” `LabelRegistry.async_create()` removed the `label_id` keyword argument; now tries with fallback

### Added
- Restart overlay with spinner animation shown while Home Assistant restarts (fixes #183)

### Fixed
- Copy button broken on HTTP (non-HTTPS) setups â€” `navigator.clipboard.writeText` requires HTTPS; added `execCommand('copy')` fallback so copy works on plain HTTP local installs

---

## [0.5.3] â€” 2026-05-21 21:59 +0200

### Fixed
- `CLOUD_PROVIDER_ANTHROPIC` `NameError` in the `www/` copy of `http_api.py` â€” missing import caused a 500 error when Anthropic was selected

---

## [0.5.2] â€” 2026-05-21 21:44 +0200

### Fixed
- Intent classifier false positives causing the wrong response mode to be selected (closes #113)
- Chat store migration failed silently when the storage write errored; now rolls back in-memory state and surfaces the error (closes #114)

---

## [0.5.1] â€” 2026-05-21 21:07 +0200

### Fixed
- 3 flaky tests caused by test-ordering state corruption in the debug and summarize test files
- Hardcoded `v0.4.5` version string in the startup log replaced with the current manifest version
- `_LOGGER.warning()` used for routine informational startup messages replaced with `_LOGGER.info()` to reduce log noise

---

## [0.5.0] â€” 2026-05-21 21:00 +0200

### Fixed
- Knowledge store deduplication: spurious signal-word false-matches removed from TF-IDF index
- Proposal review card alias display and button entity preference in action proposals (closes #148)
- `get_entity_state` serialises `datetime` attributes correctly (closes #146)
- Dashboard indexer label quality and alias format improved (closes #147)
- Button entity `press` recipe and auto-alias generation for button-class entities (closes #145)
- Self-update endpoint used the wrong `aiohttp` session; error messages improved (closes #144)

---

## [0.4.9] â€” 2026-05-21 20:51 +0200

### Fixed
- Options flow discarded all existing config keys when only a subset of form sections were submitted, breaking settings after reconfigure (closes #167)

---

## [0.4.8] â€” 2026-05-21 20:48 +0200

### Fixed
- Synthesis (summarise) AI call always routed to the local Ollama provider regardless of the configured cloud provider setting (closes #166)

---

## [0.4.7] â€” 2026-05-21 20:42 +0200

### Security
- Path validation in blueprint/source loader: replaced fragile `str.startswith()` check with `Path.relative_to()` to prevent path-traversal when reading user-supplied file paths (closes #165)

---

## [0.4.6] â€” 2026-05-21 20:41 +0200

### Fixed
- Busy flag and log handler not cleared on all AI error paths â€” the panel remained permanently locked after a timeout or unhandled exception (closes #164)

---

## [0.4.5] â€” 2026-05-21 18:25 +0200

_Tag alias for v0.4.4 â€” same commit._

---

## [0.4.4] â€” 2026-05-21 18:25 +0200

### Added
- Anthropic (Claude) cloud provider: `claude-3-5-sonnet-20241022` and `claude-3-haiku-20240307` with streaming support and 429 rate-limit back-off

---

## [0.4.3] â€” 2026-05-21 18:20 +0200

### Added
- General cloud-provider configuration layer (`cloud_provider.py`) supporting Azure AI Foundry and OpenAI endpoints

---

## [0.4.2] â€” 2026-05-21 17:42 +0200

### Fixed
- Azure AI Foundry 429 (rate limit) responses now trigger exponential back-off and surface a clean error message in the chat panel rather than a raw HTTP error

---

## [0.4.1] â€” 2026-05-21 17:06 +0200

### Fixed
- Config entry `options` not merged into the active config dict at setup â€” cloud provider settings were silently ignored after a Home Assistant restart

---

## [0.4.0] â€” 2026-05-21 16:41 +0200

### Added
- Azure AI Foundry cloud provider: route AI calls to Azure Foundry by setting `kyber_cloud_provider: azure_ai_foundry` in the integration options

---

## [0.3.9] â€” 2026-05-21 16:36 +0200

### Fixed
- Regression-test capture saves the snapshot to the HA config directory instead of the integration source tree, making it writable in production installations

---

## [0.3.8] â€” 2026-05-21 16:29 +0200

### Fixed
- Disambiguated entity chips showed display names instead of entity IDs in the click payload
- `TOOL_RESULT` content no longer leaks into the rendered chat response (visible as raw JSON fragments)

---

## [0.3.7] â€” 2026-05-21 16:06 +0200

### Fixed
- `SyntaxError` in `http_api.py` was blocking startup on recent Python versions
- Integration version is now logged at startup for easier diagnostics

---

## [0.3.6] â€” 2026-05-21 14:56 +0200

### Added
- Entity disambiguation as interactive chips: when a query matches multiple entities, Kyber shows a "toon meer" (show more) collapsible chip list with one-click selection
- Retry button on timeout errors in the chat panel
- Copy button on all chat messages
- Thumbs up / thumbs down feedback on AI answers
- Visual feedback when an entity alias is saved to memory

---

## [0.3.5] â€” 2026-05-21 13:36 +0200

### Fixed
- Resolved correct Ollama endpoint and model per AI-task entity when multiple entities are configured across different servers

---

## [0.3.4] â€” 2026-05-21 13:01 +0200

### Added
- Ollama debug pre-flight shows the configured endpoint URL and all currently-pulled models
- Warning banner in the panel when the configured Ollama model is not pulled

---

## [0.3.3] â€” 2026-05-21 11:28 +0200

### Added
- Model name included in `[AIâ†’]` / `[AIâ†]` debug log lines for easier multi-model diagnostics
- Debug panel now visible in normal chat mode when debug is enabled (not only in the dedicated debug-mode view)
- Warning banner when the AI task entity is unavailable or misconfigured

---

## [0.3.2] â€” 2026-05-21 11:13 +0200

### Fixed
- Kyber logger not set to `DEBUG` level when debug mode is enabled â€” detailed request/response logs were being silently discarded at the default `WARNING` level

---

## [0.3.1] â€” 2026-05-21 10:08 +0200

### Added
- Chat preemption: sending a new message while an AI call is in-flight immediately cancels the in-flight request
- Paused status indicator shown while waiting for a queued message to be processed
- Exponential back-off on AI call retries (closes #162)

---

## [0.3.0] â€” 2026-05-21 09:34 +0200

### Added
- Live progress indicator card: each tool call and AI round-trip is shown in real time as it happens
- "Run now" buttons on individual progress steps for immediate re-execution
- AI call request/response debug logging visible in the debug panel
- Deep analyzer AI call timeout increased from 60 s to 300 s

---

## [0.2.26] â€” 2026-05-21 00:02 +0200

### Fixed
- Options flow missing fields caused a `vol.Any` serialisation error when saving settings

---

## [0.2.25] â€” 2026-05-20 23:54 +0200

### Fixed
- Single-step config flow broken after recent refactor
- Narrator entity schema validation error on empty narrator-entity field

---

## [0.2.24] â€” 2026-05-20 23:47 +0200

### Changed
- Collapsed 2-step config flow into a single step for a simpler initial setup experience

---

## [0.2.22] â€” 2026-05-20 23:22 +0200

### Fixed
- `vol.Any` schema rejected extra keys in the `model_config` sub-dict

---

## [0.2.21] â€” 2026-05-20 23:01 +0200

### Fixed
- Main Kyber panel not removed on integration unload/remove â€” stale sidebar entry persisted across HA restarts

---

## [0.2.20] â€” 2026-05-20 22:50 +0200

### Fixed
- Missing `reconfigure` step in `translations/en.json` caused a UI error when trying to reconfigure the integration

---

## [0.2.19] â€” 2026-05-20 22:34 +0200

### Added
- `async_step_reconfigure` support in the config flow â€” allows editing the Ollama connection without removing and re-adding the integration

---

## [0.2.18] â€” 2026-05-20 21:58 +0200

### Fixed
- Signal-word filter in `async_pick_relevant` was incorrectly rejecting valid memory matches on common query words

---

## [0.2.17] â€” 2026-05-20 21:33 +0200

### Fixed
- `low_quality` narrator entries excluded from TF-IDF index to improve retrieval precision and reduce noise (closes #155)
- `entity_explorer` knowledge cache evicted after each narrator save to keep integration-context entries fresh

---

## [0.2.16] â€” 2026-05-20 21:10 +0200

### Added
- Device context expansion: memory-matched entity aliases are resolved to their full device context before the prompt is assembled

---

## [0.2.15] â€” 2026-05-20 20:59 +0200

### Fixed
- Stop 401 poll storm when the HA session expires â€” the progress-poller now backs off instead of flooding requests
- Debug panel JSON parse error guarded against malformed responses

---

## [0.2.14] â€” 2026-05-20 20:16 +0200

### Added
- Learning pipeline quick wins: noise filtering, helper and template indexing in the integration explorer (closes #149)
- Playwright UI tests for previously-uncovered frontend features (closes #152)
- Feature screenshots added to documentation (closes #151)

---

## [0.2.13] â€” 2026-05-20 18:56 +0200

### Fixed
- Review card alias display and button entity preference in action proposals (closes #148)

---

## [0.2.12] â€” 2026-05-20 18:44 +0200

### Fixed
- Dashboard indexer label quality and alias format improved (closes #147)

---

## [0.2.11] â€” 2026-05-20 18:23 +0200

### Fixed
- `get_entity_state` serialises `datetime` attributes correctly (closes #146)
- Button entity `press` recipe and auto-alias generation for button-class entities (closes #145)

---

## [0.2.10] â€” 2026-05-20 18:05 +0200

### Added
- Proposal review flow with label descriptions (closes #136)

### Fixed
- Self-update endpoint used the wrong `aiohttp` session; error messages improved (closes #144)

---

## [0.2.9] â€” 2026-05-20 17:32 +0200

### Added
- Multi-language translation: AI language detection now injects locale-specific vocabulary hints for French, German, Spanish, Italian, and Portuguese

### Fixed
- Context loop prevention: AI log entries already in the prompt are no longer re-fetched on the next call, eliminating runaway context growth (closes #143)

---

## [0.2.8] â€” 2026-05-20 14:09 +0200

### Performance
- System prompt compressed 31% (âˆ’2 007 tokens) by removing redundant tool descriptions and merging static instruction blocks

---

## [0.2.7] â€” 2026-05-20 14:01 +0200

### Added
- Zones support: zone entity states, occupancy context, and person location tracking via new `get_person_locations` tool

---

## [0.2.6] â€” 2026-05-20 13:51 +0200

### Fixed
- `SyntaxError` in `__init__.py` blocking startup
- Incomplete area context now logs a warning rather than silently producing an empty prompt

---

## [0.2.5] â€” 2026-05-20 13:43 +0200

### Added
- Review queue in the chat pane with compact card design and bulk approve/reject rules

---

## [0.2.4] â€” 2026-05-20 13:29 +0200

### Fixed
- Review flow approve/reject button endpoints corrected after API rename

---

## [0.2.3] â€” 2026-05-20 13:20 +0200

### Fixed
- Missing `_timeAgo` declaration in `debug-mixin.js` caused a `ReferenceError` that blocked panel initialisation

---

## [0.2.2] â€” 2026-05-20 12:01 +0200

### Added
- Memory review flow: proposed memory edits are shown to the user for approval before being saved
- HACS Action and Hassfest validation CI workflows (required for HACS default-store submission)

---

## [0.2.1] â€” 2026-05-20 11:11 +0200

### Fixed
- Domain-intent boost in memory retrieval was not applied â€” relevant domain entries were ranked too low
- Media player search hint missing from entity vocabulary

---

## [0.2.0] â€” 2026-05-20 08:08 +0200

### Added
- `/update force` â€” self-update directly from the latest GitHub release, bypassing HACS
- Dutch kitchen-appliance vocabulary extended to all supported AI languages
- `search_automations` tool for schedule and timing questions
- Conversation-driven area discovery with language-agnostic prompts (closes #135)
- Ollama health check on startup with response timing and token-count logging
- Model help links in the debug status panel
- Entity narrator batch size capped at 10 based on benchmarking results
- Entity narrator model name, display name, and server URL shown in debug panel

### Fixed
- Hallucinated narrator aliases filtered via plausibility scoring before saving
- Deep-analyzer extracted facts now always include `entity_ids` in tags and content fields

---

## [0.1.20] â€” 2026-05-16 19:07 +0200

### Fixed
- Action plans that referenced bogus entity IDs are now rescued by matching the area name and substituting valid entities

---

## [0.1.19] â€” 2026-05-16 18:20 +0200

### Added
- State filter on `list_entities` tool â€” filter by state value (e.g. `on`, `off`, `unavailable`)
- New `list_entities_without_area` tool for area-assignment workflows
- Tool name alias resolution â€” the AI can use alternate names for tools without triggering an error

---

## [0.1.18] â€” 2026-05-16 18:05 +0200

### Fixed
- `T00L_CALL` zero/O regex: the AI sometimes writes `T00L_CALL` with a zero instead of the letter O â€” both are now handled
- Intent classifier over-triggering on borderline messages reduced via stricter matching

---

## [0.1.17] â€” 2026-05-16 17:51 +0200

### Added
- Brand icons bundled in `custom_components/kyber/brand/` for HACS store display

---

## [0.1.15] â€” 2026-05-16 17:44 +0200

### Fixed
- AI was responding without tool calls when it should always call tools for real home data; strict enforcement rule added to the system prompt

---

## [0.1.14] â€” 2026-05-16 17:41 +0200

### Added
- Thinking animation (spinner) displayed in the chat panel while the AI is processing

---

## [0.1.13] â€” 2026-05-16 17:38 +0200

### Fixed
- AI was narrating its own tool calls aloud; tool result messages are now stripped from the rendered chat output
- Fabricated entity IDs in AI responses detected and replaced with an error notice

---

## [0.1.12] â€” 2026-05-16 17:26 +0200

### Fixed
- Misrouted `open_editor` plans now rescued and redirected to the correct editor endpoint

---

## [0.1.11] â€” 2026-05-16 17:22 +0200

### Fixed
- Strip AI response preamble (e.g. "Certainly!", "Of course!") before rendering in chat
- Placeholder text and fabricated entity IDs removed from rendered responses

---

## [0.1.10] â€” 2026-05-16 17:10 +0200

### Added
- Intent classification: pre-classify each user message into `action`, `question`, `editor`, or `info` to select the right response format

---

## [0.1.9] â€” 2026-05-16 17:00 +0200

### Fixed
- Added `issue_tracker` field to `manifest.json` and root brand assets required for HACS default-store submission (closes #26)

---

## [0.1.5] â€” 2026-05-16 16:16 +0200

### Added
- Smart context: area-based home-state snapshot â€” only entities relevant to the user's request (by area) are included in the AI prompt; a context badge shows which areas were selected

---

## [0.1.4] â€” 2026-05-16 15:44 +0200

### Fixed
- Removed `/no_think` system-prompt suffix â€” it was producing raw token-ID output on llama3

---

## [0.1.3] â€” 2026-05-16 15:24 +0200

### Fixed
- Added `/no_think` suffix to the system prompt to prevent qwen3 thinking-mode tokens from leaking into chat responses

---

## [0.1.2] â€” 2026-05-16 14:53 +0200

### Added
- Persistent chat history: conversation context survives panel reloads and Home Assistant restarts (closes #24)

---

## [0.1.1] â€” 2026-05-16 11:16 +0200

### Changed
- Version bump and HACS metadata corrections post-submission

---

## [0.1.0] â€” 2026-05-16 10:51 +0200

### Added
- **Initial release** â€” Kyber submitted to HACS custom repositories
- Local AI chat panel for Home Assistant, powered by Ollama
- Proposal cards with one-click Undo
- Automation and script YAML editor with CodeMirror 6
- Dashboard editor (create and edit Lovelace dashboards as YAML)
- Slash commands: `/dashboard`, `/automation`, `/script`, `/blueprint`, `/area`, `/memory`, `/update`
- AI Entity Narrator â€” background batch narration of all entities with alias generation
- TF-IDF hybrid memory retrieval with cosine similarity
- Tool-calling loop (up to 5 rounds) with duplicate call detection
- Named conversation sessions with rolling history and automatic compaction
- Kyber Debug panel (`/kyber-debug`) with Memory, Last Turn, Status, Logs, and Tests tabs
- Debug bundle download (ZIP containing the full system prompt, tool log, memory picks, and AI response)
