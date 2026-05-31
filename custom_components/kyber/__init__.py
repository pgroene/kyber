"""The kyber integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.panel_custom import async_register_panel

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_NARRATOR_AI_TASK_ENTITY_ID,
    CONF_ENABLE_DEBUG_VIEWS,
    CONF_ENABLE_MCP,
    DEFAULT_ENABLE_MCP,
    CONF_INITIAL_DEEP_LEARNING_RUNS,
    CONF_INITIAL_LEARNING_DONE,
    CONF_INITIAL_LEARNING_VERSION,
    CONF_NARRATOR_ENABLED,
    CONF_NARRATOR_MAX_BATCH,
    CONF_NARRATOR_MAX_TOKENS,
    CONF_NARRATOR_INTERVAL_DAYS,
    CONF_NARRATOR_LAST_RUN_TS,
    CONF_DEEP_LEARNING_INTERVAL_DAYS,
    CONF_DEEP_LEARNING_LAST_RUN_TS,
    CONF_DEEP_LEARNING_MAX_BATCH,
    CONF_RUN_INITIAL_ANALYZE,
    CURRENT_INITIAL_LEARNING_VERSION,
    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    DEFAULT_NARRATOR_ENABLED,
    DEFAULT_NARRATOR_MAX_BATCH,
    DEFAULT_NARRATOR_MAX_TOKENS,
    DEFAULT_NARRATOR_INTERVAL_DAYS,
    DEFAULT_DEEP_LEARNING_INTERVAL_DAYS,
    DEFAULT_DEEP_LEARNING_MAX_BATCH,
    DEFAULT_RUN_INITIAL_ANALYZE,
    DOMAIN,
    KNOWLEDGE_SCHEMA_VERSION,
)
from .analyzer import analyze_automations as _analyze_automations
from . import deep_analyzer as _deep
from .knowledge import get_knowledge_store
from .http_api import KyberView, KyberSaveView, KyberExecuteView, KyberSummarizeView, KyberHistoryView, KyberSessionsView, KyberSessionNameView, KyberProgressView, KyberKnowledgeView, KyberKnowledgeEntryView, KyberKnowledgeAnalyzeView, KyberKnowledgeDeepAnalyzeView, KyberKnowledgeFeedbackView, KyberKnowledgePurgeView, KyberDebugLastTurnView, KyberDebugToolHistoryView, KyberDebugStatusView, KyberDebugBundleView, KyberBugReportView, KyberDebugModeView, KyberPromptTestsView, KyberPromptTestsRunView, KyberPromptTestsCaptureView, KyberPromptTestsRegenerateView, KyberLabelsView, KyberAreaSuggestionsView, KyberProposalApproveView, KyberPingView, KyberSelfUpdateView, KyberNarratorRunView, KyberExplorerRunView, KyberClassicLogView, KyberBlueprintView
from .action_history import KyberActionHistoryView, KyberActionHistoryUndoView, KyberActionHistoryEntryView
from .debug_and_diagnostics import KyberHomeExportView, KyberMemoryExportView, KyberGlobalLogHandler, KyberDebugLogsView
from .mcp import KyberMCPView, KyberMcpLogView

_LOGGER = logging.getLogger(__name__)

type KyberConfigEntry = ConfigEntry[None]

_WWW_DIR = Path(__file__).parent / "www"

_DEBUG_MODE_KEY = "kyber_debug_mode"


async def _async_run_initial_learning(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Run AI-powered analysis of automations/scripts to populate the knowledge store.

    Guarded by a version number so it re-runs automatically when the learning
    logic is improved (bump CURRENT_INITIAL_LEARNING_VERSION in const.py).
    Uses force=True so the AI is called on every item regardless of whether
    the YAML has changed since the last run.
    """
    import asyncio

    data = dict(entry.data)
    stored_version = int(data.get(CONF_INITIAL_LEARNING_VERSION, 0))
    if stored_version >= CURRENT_INITIAL_LEARNING_VERSION:
        _LOGGER.debug(
            "Kyber initial learning already at v%d — skipping", stored_version
        )
        return

    ai_entity_id = str(data.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    run_initial_analyze = bool(
        data.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE)
    )
    deep_runs = max(
        1,
        min(
            10,
            int(
                data.get(
                    CONF_INITIAL_DEEP_LEARNING_RUNS,
                    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
                )
            ),
        ),
    )

    # Wait for the AI task entity to become available (other integrations may
    # load after Kyber). Retry for up to 60 seconds before giving up.
    _LOGGER.warning(
        "Kyber initial learning v%d: waiting for AI entity '%s'…",
        CURRENT_INITIAL_LEARNING_VERSION,
        ai_entity_id,
    )
    for _attempt in range(12):
        if hass.states.get(ai_entity_id) is not None:
            break
        await asyncio.sleep(5)
    else:
        _LOGGER.warning(
            "Kyber initial learning: AI entity '%s' not available after 60s — aborting",
            ai_entity_id,
        )
        return

    _LOGGER.warning(
        "Kyber initial learning v%d starting — analyze=%s, deep_runs=%d, ai_entity=%s",
        CURRENT_INITIAL_LEARNING_VERSION,
        run_initial_analyze,
        deep_runs,
        ai_entity_id,
    )

    if run_initial_analyze:
        _LOGGER.warning("Kyber initial learning: running fast automation analysis…")
        try:
            await hass.async_add_executor_job(_analyze_automations, hass)
            _LOGGER.warning("Kyber initial learning: fast analysis complete")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Kyber initial analyze run failed: %s", err)

    total_facts = 0
    for i in range(deep_runs):
        _LOGGER.warning(
            "Kyber initial learning: AI deep-analysis run %d/%d…", i + 1, deep_runs
        )
        try:
            # force=True: analyze every automation/script even if hash unchanged,
            # retiring old knowledge entries first to avoid duplicates.
            result = await _deep.analyze_pending(
                hass, ai_entity_id=ai_entity_id, limit=5, force=True
            )
            n_analyzed = len(result.get("analyzed", []))
            n_facts = sum(
                len(a.get("fact_ids", [])) for a in result.get("analyzed", [])
            )
            total_facts += n_facts
            _LOGGER.warning(
                "Kyber initial learning: run %d/%d — %d items analyzed, %d facts stored"
                " (skipped_unchanged=%d, errors=%d)",
                i + 1, deep_runs, n_analyzed, n_facts,
                result.get("skipped_unchanged", 0),
                len(result.get("errors", [])),
            )
            for item in result.get("analyzed", []):
                if item.get("facts"):
                    _LOGGER.warning(
                        "  [%s] '%s' → %d fact(s): %s",
                        item["kind"],
                        item["ident"],
                        len(item["facts"]),
                        " | ".join(
                            f.get("content", "")[:100]
                            for f in item["facts"]
                        ),
                    )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Kyber initial deep learning run %d/%d failed: %s", i + 1, deep_runs, err
            )

    data[CONF_INITIAL_LEARNING_VERSION] = CURRENT_INITIAL_LEARNING_VERSION
    data[CONF_INITIAL_LEARNING_DONE] = True
    hass.config_entries.async_update_entry(entry, data=data)
    _LOGGER.warning(
        "Kyber initial learning v%d complete ✓ — %d total facts stored across %d runs",
        CURRENT_INITIAL_LEARNING_VERSION,
        total_facts,
        deep_runs,
    )


async def _async_explore_integrations(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Background task: explore all loaded integrations and store knowledge facts.

    Called via async_at_start so HA has already finished loading when we run.
    Idempotent — skips already-explored ones.

    After Phase 1+2 completes, fires Phase 3 (entity narrator) if an AI
    task entity is configured.
    """
    import asyncio
    from homeassistant.helpers import entity_registry as er
    from .knowledge import get_knowledge_store
    from .integration_explorer import async_startup_explore_all

    # --- Schema-version upgrade check ---
    # If KNOWLEDGE_SCHEMA_VERSION was bumped, wipe all auto-generated entries so
    # they are rebuilt fresh with the new filters, prompts, and dedup logic.
    try:
        kstore = get_knowledge_store(hass)
        await kstore.async_load()
        schema_entry = (await kstore.async_search(
            subject="_knowledge_schema_version", limit=1, exclude_low_quality=False,
        ) or [None])[0]
        stored_schema_ver = int((schema_entry or {}).get("content", 0))
        if stored_schema_ver < KNOWLEDGE_SCHEMA_VERSION:
            purged = await kstore.async_purge_auto_generated()
            _LOGGER.info(
                "Kyber: schema v%d→v%d: purged %d auto-generated entries",
                stored_schema_ver, KNOWLEDGE_SCHEMA_VERSION, purged,
            )
            # Update stored version
            if schema_entry:
                schema_entry["content"] = str(KNOWLEDGE_SCHEMA_VERSION)
                schema_entry["updated"] = int(__import__("time").time())
                kstore._entries[schema_entry["id"]] = schema_entry  # noqa: SLF001
                await kstore._persist(invalidate_index=True)  # noqa: SLF001
            else:
                await kstore.async_add(
                    "general",
                    str(KNOWLEDGE_SCHEMA_VERSION),
                    subject="_knowledge_schema_version",
                    source="system",
                    _save=True,
                )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber: schema version check failed: %s", err)

    # Dedup — skips automatically if a clean-marker for the current schema version
    # is present (written after the last dedup found 0 duplicates).
    try:
        kstore = get_knowledge_store(hass)
        removed = await kstore.async_dedup(schema_version=KNOWLEDGE_SCHEMA_VERSION)
        if removed:
            _LOGGER.info("Kyber: startup dedup removed %d duplicate memory entries", removed)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber: startup dedup failed: %s", err)

    # Purge narrator aliases that fail the plausibility check (hallucinated cross-domain
    # aliases created by older narrator versions, e.g. TV child-lock → "coffee maker").
    try:
        from .entity_narrator import async_purge_implausible_aliases
        kstore = get_knowledge_store(hass)
        await async_purge_implausible_aliases(kstore)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber: alias plausibility purge failed: %s", err)

    try:
        kstore = get_knowledge_store(hass)
        entity_reg = er.async_get(hass)
        count = await async_startup_explore_all(hass, kstore, entity_reg)
        _LOGGER.info("Kyber: integration explorer stored facts for %d integrations", count)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber: integration explorer failed: %s", err)

    # Index dashboard entities — gives the narrator human-readable card names
    # for cryptic entity IDs (e.g. switch.0xa4c138... → "Espresso").
    try:
        from .dashboard_indexer import async_index_dashboard_entities, get_dashboard_entity_names, async_store_dashboard_labels
        await async_index_dashboard_entities(hass)
        dashboard_names = get_dashboard_entity_names(hass)
        kstore = get_knowledge_store(hass)
        label_count = await async_store_dashboard_labels(hass, kstore)
        _LOGGER.info("Kyber: dashboard indexer found %d named entities, stored %d label entries", len(dashboard_names), label_count)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber: dashboard indexer failed: %s", err)
        dashboard_names = {}

    # Phase 3: AI narrator — only if enabled and an AI task entity is configured.
    ai_entity_id = str((entry.data or {}).get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    if not ai_entity_id:
        config = {**entry.data, **(entry.options or {})}
        ai_entity_id = str(config.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    if ai_entity_id:
        import time as _time
        config = {**entry.data, **(entry.options or {})}
        narrator_enabled = bool(config.get(CONF_NARRATOR_ENABLED, DEFAULT_NARRATOR_ENABLED))
        if not narrator_enabled:
            _LOGGER.info("Kyber: narrator disabled via settings — skipping")
        else:
            max_batch = int(config.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH))
            narrator_max_tokens = int(config.get(CONF_NARRATOR_MAX_TOKENS, DEFAULT_NARRATOR_MAX_TOKENS))
            narrator_ai_entity_id = str(config.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip() or ai_entity_id
            narrator_interval_days = int(config.get(CONF_NARRATOR_INTERVAL_DAYS, DEFAULT_NARRATOR_INTERVAL_DAYS))

            # Read last-run timestamp from entry.data so it persists across restarts
            narrator_last_run = float(entry.data.get(CONF_NARRATOR_LAST_RUN_TS, 0))
            narrator_interval_secs = narrator_interval_days * 86400
            time_since_narrator = _time.time() - narrator_last_run
            if narrator_last_run > 0 and time_since_narrator < narrator_interval_secs:
                _LOGGER.info(
                    "Kyber: narrator skipped — last run %.1fh ago, interval is %dd (%.1fh remaining)",
                    time_since_narrator / 3600,
                    narrator_interval_days,
                    (narrator_interval_secs - time_since_narrator) / 3600,
                )
            else:
                narrator_lock = hass.data.get("kyber_narrator_lock")
                if narrator_lock and narrator_lock.locked():
                    _LOGGER.info("Kyber: narrator skipped — another run is already in progress")
                else:
                    _NARRATOR_RETRY_DELAY = 600   # 10 minutes between retries
                    _NARRATOR_MAX_RETRIES = 3
                    async with narrator_lock:
                        for attempt in range(1 + _NARRATOR_MAX_RETRIES):
                            try:
                                from .entity_narrator import async_narrate_entities
                                from .knowledge import get_knowledge_store as _gks
                                from homeassistant.helpers import entity_registry as _er
                                from .model_stats import record_run as _record_run
                                kstore = _gks(hass)
                                entity_reg = _er.async_get(hass)
                                narrator_stats = await async_narrate_entities(
                                    hass, kstore, entity_reg, narrator_ai_entity_id,
                                    max_batch=max_batch,
                                    narrator_max_tokens=narrator_max_tokens,
                                    dashboard_names=dashboard_names,
                                )
                                errors = narrator_stats.get("errors", 0)
                                _LOGGER.info(
                                    "Kyber: narrator complete (attempt %d) — %d accepted, %d low-quality, "
                                    "%d parse failures, %d errors (batch_size=%d)",
                                    attempt + 1,
                                    narrator_stats.get("accepted", 0),
                                    narrator_stats.get("low_quality", 0),
                                    narrator_stats.get("parse_failures", 0),
                                    errors,
                                    narrator_stats.get("batch_size_used", 0),
                                )
                                if errors == 0 or attempt >= _NARRATOR_MAX_RETRIES:
                                    hass.config_entries.async_update_entry(
                                        entry, data={**entry.data, CONF_NARRATOR_LAST_RUN_TS: _time.time()}
                                    )
                                    _record_run(hass, "narrator", interval_secs=narrator_interval_secs)
                                    break
                                _LOGGER.warning(
                                    "Kyber: narrator had %d errors — retrying in %ds (attempt %d/%d)…",
                                    errors, _NARRATOR_RETRY_DELAY, attempt + 1, _NARRATOR_MAX_RETRIES,
                                )
                                await asyncio.sleep(_NARRATOR_RETRY_DELAY)
                            except Exception as err:  # noqa: BLE001
                                _LOGGER.warning("Kyber: entity narrator failed (attempt %d): %s", attempt + 1, err)
                                if attempt < _NARRATOR_MAX_RETRIES:
                                    await asyncio.sleep(_NARRATOR_RETRY_DELAY)
                                break

        # Deep learning interval-based scheduling
        deep_learning_interval_days = int(config.get(CONF_DEEP_LEARNING_INTERVAL_DAYS, DEFAULT_DEEP_LEARNING_INTERVAL_DAYS))
        deep_last_run = float(entry.data.get(CONF_DEEP_LEARNING_LAST_RUN_TS, 0))
        deep_interval_secs = deep_learning_interval_days * 86400
        time_since_deep = _time.time() - deep_last_run
        if deep_last_run > 0 and time_since_deep < deep_interval_secs:
            _LOGGER.info(
                "Kyber: deep learning skipped — last run %.1fh ago, interval is %dd (%.1fh remaining)",
                time_since_deep / 3600,
                deep_learning_interval_days,
                (deep_interval_secs - time_since_deep) / 3600,
            )
        else:
            deep_learning_lock = hass.data.get("kyber_deep_learning_lock")
            if deep_learning_lock and deep_learning_lock.locked():
                _LOGGER.info("Kyber: deep learning skipped — another run is already in progress")
            else:
                run_initial_analyze = bool(config.get(CONF_RUN_INITIAL_ANALYZE, DEFAULT_RUN_INITIAL_ANALYZE))
                _LOGGER.info(
                    "Kyber: scheduled deep learning run (interval=%dd, analyze=%s)",
                    deep_learning_interval_days, run_initial_analyze,
                )
                async with deep_learning_lock:
                    try:
                        from .model_stats import record_run as _record_run2
                        if run_initial_analyze:
                            await hass.async_add_executor_job(_analyze_automations, hass)
                            _LOGGER.info("Kyber: scheduled deep learning: fast analysis complete")
                        result = await _deep.analyze_pending(hass, ai_entity_id=ai_entity_id, limit=int(config.get(CONF_DEEP_LEARNING_MAX_BATCH, DEFAULT_DEEP_LEARNING_MAX_BATCH)), force=False)
                        n_analyzed = len(result.get("analyzed", []))
                        _LOGGER.info(
                            "Kyber: scheduled deep learning complete — %d items analyzed, %d errors",
                            n_analyzed, len(result.get("errors", [])),
                        )
                        hass.config_entries.async_update_entry(
                            entry, data={**entry.data, CONF_DEEP_LEARNING_LAST_RUN_TS: _time.time()}
                        )
                        _record_run2(hass, "deep_learning", interval_secs=deep_interval_secs)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("Kyber: scheduled deep learning failed: %s", err)


async def _async_seed_language_hints(hass: HomeAssistant) -> None:
    """Seed language-vocabulary hints into the knowledge store.

    Idempotent: compares the stored version number against
    ``LANG_HINTS_VERSION`` and only re-seeds when the version is higher.
    This lets us update hints by bumping the version constant.
    """
    from .language_hints import LANGUAGE_HINTS, LANG_HINTS_VERSION, LangHintEntry
    from .knowledge import get_knowledge_store

    kstore = get_knowledge_store(hass)
    await kstore.async_load()

    _VERSION_SUBJECT = "_lang_hints_version"

    # Find existing version marker
    existing_version = 0
    version_entry_id: str | None = None
    for e in kstore._entries.values():
        if e.get("subject") == _VERSION_SUBJECT and e.get("source") == "language_builtin":
            try:
                existing_version = int(e.get("content", "0"))
            except (ValueError, TypeError):
                existing_version = 0
            version_entry_id = e["id"]
            break

    if existing_version >= LANG_HINTS_VERSION:
        _LOGGER.debug("Kyber: language hints already at v%d — skipping seed", LANG_HINTS_VERSION)
        return

    # Purge stale language_hint entries from a previous version
    if existing_version > 0:
        stale = [
            eid for eid, e in list(kstore._entries.items())
            if e.get("source") == "language_builtin" and e.get("category") == "language_hint"
        ]
        for eid in stale:
            del kstore._entries[eid]
        if version_entry_id:
            kstore._entries.pop(version_entry_id, None)
        _LOGGER.info("Kyber: purged %d stale language hint entries (v%d → v%d)",
                     len(stale), existing_version, LANG_HINTS_VERSION)

    # Seed all language hints
    total = 0
    for lang_code, lang_data in LANGUAGE_HINTS.items():
        for hint in lang_data["hints"]:
            await kstore.async_add(
                "language_hint",
                hint.content,
                subject=hint.subject,
                tags=[lang_code, "language_hint", lang_data["name"].lower()],
                source="language_builtin",
                confidence=1.0,
            )
            total += 1

    # Store version marker
    await kstore.async_add(
        "general",
        str(LANG_HINTS_VERSION),
        subject=_VERSION_SUBJECT,
        source="language_builtin",
        confidence=1.0,
    )
    _LOGGER.info(
        "Kyber: seeded %d language hint entries (v%d) for: %s",
        total,
        LANG_HINTS_VERSION,
        ", ".join(LANGUAGE_HINTS),
    )


def _resolve_debug_enabled(entry: ConfigEntry) -> bool:
    """Resolve effective debug-views setting for an entry.

    Precedence: entry.options → entry.data → fallback True.

    The fallback True preserves the experience for entries that existed
    BEFORE this option was introduced (they had no key anywhere). New
    entries get the key written to entry.data via the config flow, so
    they default to False as the user requested.
    """
    if CONF_ENABLE_DEBUG_VIEWS in entry.options:
        return bool(entry.options[CONF_ENABLE_DEBUG_VIEWS])
    if CONF_ENABLE_DEBUG_VIEWS in entry.data:
        return bool(entry.data[CONF_ENABLE_DEBUG_VIEWS])
    # Pre-existing entry from before the option existed — preserve previous behavior
    return True


_NARRATOR_ONLY_KEYS: frozenset[str] = frozenset({CONF_NARRATOR_MAX_BATCH})

_BG_TASKS_KEY = "kyber_bg_tasks"


def _make_update_listener() -> Any:
    """Return an update listener that correctly diffs consecutive options snapshots."""
    state: dict[str, Any] = {"prev_opts": None}

    async def _listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
        new_opts = entry.options or {}
        if state["prev_opts"] is None:
            # First call: use entry.data as baseline (initial setup values).
            state["prev_opts"] = dict(entry.data)
        prev_opts = state["prev_opts"]
        changed_keys = {
            k for k in set(prev_opts) | set(new_opts)
            if prev_opts.get(k) != new_opts.get(k)
        }
        state["prev_opts"] = dict(new_opts)
        if changed_keys and changed_keys.issubset(_NARRATOR_ONLY_KEYS):
            _LOGGER.debug(
                "Kyber: narrator-only options changed %s — skipping reload", changed_keys
            )
            return
        await hass.config_entries.async_reload(entry.entry_id)

    return _listener


async def async_setup_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Set up Kyber from a config entry."""
    config = {**entry.data, **(entry.options or {})}
    import json as _json
    _manifest_path = Path(__file__).parent.joinpath("manifest.json")
    _manifest_text = await hass.async_add_executor_job(
        _manifest_path.read_text, "utf-8"
    )
    _version = _json.loads(_manifest_text)["version"]
    _LOGGER.info("Kyber: loading integration v%s", _version)

    debug_enabled = _resolve_debug_enabled(entry)
    hass.data[_DEBUG_MODE_KEY] = debug_enabled
    # Store full config so background tasks (summarize, session_name, fact_extract)
    # can fall back to Azure when the local entity doesn't support thinking mode.
    hass.data["kyber_config"] = config
    # Store AI entity ID so the debug status endpoint can display it.
    hass.data["kyber_ai_task_entity"] = config.get(CONF_AI_TASK_ENTITY_ID, "")
    # Also store the narrator entity (falls back to chat entity if not separately configured).
    _narrator_eid = str({**entry.data, **(entry.options or {})}.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip()
    hass.data["kyber_narrator_ai_task_entity"] = _narrator_eid or config.get(CONF_AI_TASK_ENTITY_ID, "")
    # Initialise area assignment report queue.
    from .const import DOMAIN as _DOMAIN
    from .area_assignment import AREA_REPORTS_KEY
    if _DOMAIN not in hass.data or not isinstance(hass.data.get(_DOMAIN), dict):
        hass.data[_DOMAIN] = {}
    hass.data[_DOMAIN].setdefault(AREA_REPORTS_KEY, [])

    # Initialize per-agent asyncio locks to prevent concurrent runs
    import asyncio as _asyncio_locks
    hass.data.setdefault("kyber_narrator_lock", _asyncio_locks.Lock())
    hass.data.setdefault("kyber_deep_learning_lock", _asyncio_locks.Lock())
    # Initialize AI-busy flags (False = no background AI call in progress)
    hass.data["kyber_narrator_ai_busy"] = False
    hass.data["kyber_deep_learning_ai_busy"] = False

    hass.http.register_view(KyberView(config))
    hass.http.register_view(KyberProgressView())
    hass.http.register_view(KyberHistoryView())
    hass.http.register_view(KyberSessionsView())
    hass.http.register_view(KyberSessionNameView(config))
    hass.http.register_view(KyberSaveView())
    hass.http.register_view(KyberExecuteView())
    hass.http.register_view(KyberActionHistoryView())
    hass.http.register_view(KyberActionHistoryUndoView())
    hass.http.register_view(KyberActionHistoryEntryView())
    hass.http.register_view(KyberSummarizeView(config))
    hass.http.register_view(KyberKnowledgeView())
    hass.http.register_view(KyberKnowledgeEntryView())
    hass.http.register_view(KyberKnowledgeAnalyzeView())
    hass.http.register_view(KyberKnowledgeDeepAnalyzeView(config))
    hass.http.register_view(KyberKnowledgeFeedbackView())
    hass.http.register_view(KyberKnowledgePurgeView())
    hass.http.register_view(KyberDebugLastTurnView())
    hass.http.register_view(KyberDebugToolHistoryView())
    hass.http.register_view(KyberDebugStatusView())
    hass.http.register_view(KyberDebugBundleView())
    hass.http.register_view(KyberBugReportView())
    hass.http.register_view(KyberDebugModeView())
    hass.http.register_view(KyberHomeExportView())
    hass.http.register_view(KyberMemoryExportView())
    hass.http.register_view(KyberDebugLogsView())
    hass.http.register_view(KyberPromptTestsView())
    hass.http.register_view(KyberPromptTestsRunView())
    hass.http.register_view(KyberPromptTestsCaptureView())
    hass.http.register_view(KyberPromptTestsRegenerateView())
    hass.http.register_view(KyberLabelsView())
    hass.http.register_view(KyberAreaSuggestionsView())
    hass.http.register_view(KyberProposalApproveView())
    hass.http.register_view(KyberPingView())
    hass.http.register_view(KyberSelfUpdateView())
    hass.http.register_view(KyberNarratorRunView(config))
    hass.http.register_view(KyberExplorerRunView())
    mcp_enabled = bool(
        entry.options.get(CONF_ENABLE_MCP, entry.data.get(CONF_ENABLE_MCP, DEFAULT_ENABLE_MCP))
    )
    if mcp_enabled:
        hass.http.register_view(KyberMCPView(config))
        hass.http.register_view(KyberMcpLogView())
    hass.http.register_view(KyberClassicLogView())
    hass.http.register_view(KyberBlueprintView())
    hass.http.register_view(KyberActionHistoryView())
    hass.http.register_view(KyberActionHistoryUndoView())
    hass.http.register_view(KyberActionHistoryEntryView())

    # Install global log handler + set logger level
    _kyber_root = logging.getLogger("custom_components.kyber")
    if debug_enabled:
        _kyber_root.setLevel(logging.DEBUG)
    else:
        _kyber_root.setLevel(logging.WARNING)
    _global_handler = KyberGlobalLogHandler(hass)
    _kyber_root.addHandler(_global_handler)
    hass.data["kyber_global_log_handler"] = _global_handler

    # Serve frontend files from the component's www/ directory.
    # This makes HACS installs work without manual file copying.
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/local/kyber", str(_WWW_DIR), cache_headers=True)]
    )

    try:
        await async_register_panel(
            hass,
            frontend_url_path="kyber",
            webcomponent_name="kyber-panel",
            sidebar_title="Kyber",
            sidebar_icon="mdi:robot",
            module_url="/local/kyber/kyber-panel.js?v=324",
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Panel registration skipped (test environment)")

    # Only register the separate "Kyber Debug" sidebar entry when debug views
    # are enabled — otherwise the panel would appear with nothing useful.
    if debug_enabled:
        try:
            await async_register_panel(
                hass,
                frontend_url_path="kyber-debug",
                webcomponent_name="kyber-panel",
                sidebar_title="Kyber Debug",
                sidebar_icon="mdi:bug",
                module_url="/local/kyber/kyber-panel.js?v=324",
                config={"mode": "debug"},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Debug panel registration skipped (test environment)")

    # Always schedule the initial learning task; the function itself guards
    # against re-running via CONF_INITIAL_LEARNING_DONE.
    _bg_task_list: list[Any] = []
    hass.data[_BG_TASKS_KEY] = _bg_task_list
    _bg_task_list.append(hass.async_create_task(_async_run_initial_learning(hass, entry)))

    # Seed language vocabulary hints and explore integrations AFTER HA has
    # fully started — this avoids contending with other integration setups.
    # Use asyncio.ensure_future (not hass.async_create_task) so HA's bootstrap
    # tracker doesn't wait for these long-running background jobs and log a
    # spurious "blocking startup" warning.
    import asyncio as _asyncio
    from homeassistant.helpers.start import async_at_start
    from homeassistant.core import callback as _callback

    @_callback
    def _on_ha_started(_hass: HomeAssistant) -> None:
        _bg_task_list.append(_asyncio.ensure_future(_async_seed_language_hints(_hass)))
        _bg_task_list.append(_asyncio.ensure_future(_async_explore_integrations(_hass, entry)))

    async_at_start(hass, _on_ha_started)

    entry.async_on_unload(entry.add_update_listener(_make_update_listener()))

    _LOGGER.info(
        "Kyber set up OK — AI entity: %s, debug_views=%s",
        config.get(CONF_AI_TASK_ENTITY_ID),
        debug_enabled,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Unload a config entry."""
    # Cancel any tracked background tasks started during setup.
    import asyncio as _asyncio
    _bg_tasks = hass.data.pop(_BG_TASKS_KEY, [])
    for _task in _bg_tasks:
        if not _task.done():
            _task.cancel()
            try:
                await _task
            except (_asyncio.CancelledError, Exception):
                pass
    # Remove panels so reloads and removals cleanly re-evaluate registration.
    try:
        from homeassistant.components.frontend import async_remove_panel
        async_remove_panel(hass, "kyber")
        async_remove_panel(hass, "kyber-debug")
    except Exception:  # noqa: BLE001
        pass
    # Remove global log handler
    _handler = hass.data.pop("kyber_global_log_handler", None)
    if _handler:
        logging.getLogger("custom_components.kyber").removeHandler(_handler)
    return True









