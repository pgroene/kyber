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
    CONF_INITIAL_DEEP_LEARNING_RUNS,
    CONF_INITIAL_LEARNING_DONE,
    CONF_INITIAL_LEARNING_VERSION,
    CONF_NARRATOR_MAX_BATCH,
    CONF_RUN_INITIAL_ANALYZE,
    CURRENT_INITIAL_LEARNING_VERSION,
    DEFAULT_INITIAL_DEEP_LEARNING_RUNS,
    DEFAULT_NARRATOR_MAX_BATCH,
    DEFAULT_RUN_INITIAL_ANALYZE,
    DOMAIN,
)
from .analyzer import analyze_automations as _analyze_automations
from . import deep_analyzer as _deep
from .knowledge import get_knowledge_store
from .http_api import KyberView, KyberSaveView, KyberExecuteView, KyberSummarizeView, KyberHistoryView, KyberSessionsView, KyberSessionNameView, KyberProgressView, KyberKnowledgeView, KyberKnowledgeAnalyzeView, KyberKnowledgeDeepAnalyzeView, KyberKnowledgeFeedbackView, KyberKnowledgePurgeView, KyberDebugLastTurnView, KyberDebugToolHistoryView, KyberDebugStatusView, KyberDebugBundleView, KyberBugReportView, KyberDebugModeView, KyberPromptTestsView, KyberPromptTestsRunView, KyberPromptTestsCaptureView, KyberPromptTestsRegenerateView
from .debug_and_diagnostics import KyberHomeExportView

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

    Waits a short grace period so HA finishes loading other integrations before
    we scan the entity registry. Idempotent — skips already-explored ones.

    After Phase 1+2 completes, fires Phase 3 (entity narrator) if an AI
    task entity is configured.
    """
    import asyncio
    from homeassistant.helpers import entity_registry as er
    from .knowledge import get_knowledge_store
    from .integration_explorer import async_startup_explore_all

    await asyncio.sleep(15)  # let HA finish loading other integrations
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

    # Phase 3: AI narrator — only if an AI task entity is configured.
    ai_entity_id = str((entry.data or {}).get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    if not ai_entity_id:
        config = {**entry.data, **(entry.options or {})}
        ai_entity_id = str(config.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    if ai_entity_id:
        config = {**entry.data, **(entry.options or {})}
        max_batch = int(config.get(CONF_NARRATOR_MAX_BATCH, DEFAULT_NARRATOR_MAX_BATCH))
        narrator_ai_entity_id = str(config.get(CONF_NARRATOR_AI_TASK_ENTITY_ID, "")).strip() or ai_entity_id
        _NARRATOR_RETRY_DELAY = 600   # 10 minutes between retries
        _NARRATOR_MAX_RETRIES = 3
        for attempt in range(1 + _NARRATOR_MAX_RETRIES):
            try:
                from .entity_narrator import async_narrate_entities
                from .knowledge import get_knowledge_store as _gks
                from homeassistant.helpers import entity_registry as _er
                kstore = _gks(hass)
                entity_reg = _er.async_get(hass)
                narrator_stats = await async_narrate_entities(
                    hass, kstore, entity_reg, narrator_ai_entity_id,
                    max_batch=max_batch,
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


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change — but skip reload for narrator-only tweaks.

    Changing CONF_NARRATOR_MAX_BATCH while the narrator is running would cancel
    the background task; the new run then finds all entities already narrated and
    exits immediately.  The batch size is read at the start of each narrator run,
    so we can safely absorb those changes without a reload.
    """
    old_opts = entry.options or {}
    # HA passes the new values in entry.options before calling this listener,
    # so we compare against the previous snapshot stored in entry.data.
    changed_keys = {
        k for k in set(old_opts) | set(entry.data)
        if old_opts.get(k) != entry.data.get(k)
    }
    if changed_keys and changed_keys.issubset(_NARRATOR_ONLY_KEYS):
        _LOGGER.debug(
            "Kyber: narrator-only options changed %s — skipping reload", changed_keys
        )
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Set up Kyber from a config entry."""
    config = dict(entry.data)

    debug_enabled = _resolve_debug_enabled(entry)
    hass.data[_DEBUG_MODE_KEY] = debug_enabled
    # Store AI entity ID so the debug status endpoint can display it.
    hass.data["kyber_ai_task_entity"] = config.get(CONF_AI_TASK_ENTITY_ID, "")

    hass.http.register_view(KyberView(config))
    hass.http.register_view(KyberProgressView())
    hass.http.register_view(KyberHistoryView())
    hass.http.register_view(KyberSessionsView())
    hass.http.register_view(KyberSessionNameView(config))
    hass.http.register_view(KyberSaveView())
    hass.http.register_view(KyberExecuteView())
    hass.http.register_view(KyberSummarizeView(config))
    hass.http.register_view(KyberKnowledgeView())
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
    hass.http.register_view(KyberPromptTestsView())
    hass.http.register_view(KyberPromptTestsRunView())
    hass.http.register_view(KyberPromptTestsCaptureView())
    hass.http.register_view(KyberPromptTestsRegenerateView())

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
            module_url="/local/kyber/kyber-panel.js?v=114",
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
                module_url="/local/kyber/kyber-panel.js?v=114",
                config={"mode": "debug"},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Debug panel registration skipped (test environment)")

    # Always schedule the initial learning task; the function itself guards
    # against re-running via CONF_INITIAL_LEARNING_DONE.
    hass.async_create_task(_async_run_initial_learning(hass, entry))

    # Seed language vocabulary hints into the knowledge store (idempotent).
    hass.async_create_task(_async_seed_language_hints(hass))

    # Explore all loaded integrations and store capability knowledge facts.
    # Runs in the background after startup so it doesn't block the UI.
    # Idempotent: skips integrations that already have auto-discovered facts.
    hass.async_create_task(_async_explore_integrations(hass, entry))

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    _LOGGER.warning(
        "Kyber set up OK — panel registered, AI entity: %s, debug_views=%s",
        config.get(CONF_AI_TASK_ENTITY_ID),
        debug_enabled,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KyberConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove the debug panel if we registered one so reloads can re-evaluate.
    try:
        from homeassistant.components.frontend import async_remove_panel
        async_remove_panel(hass, "kyber-debug")
    except Exception:  # noqa: BLE001
        pass
    return True

