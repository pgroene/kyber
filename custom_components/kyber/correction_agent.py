"""Correction micro-agent for Kyber.

When an action fails during plan execution, this module builds a focused
AI micro-prompt (pre-loaded with Home Assistant domain documentation) and
requests a corrected plan from the configured AI provider.

The correction agent:
- Detects failed ``call_service`` actions in the execution results
- Loads domain docs from :mod:`domain_docs` — no live tool call needed
- Sends a single-shot prompt to the AI provider configured for this entry
- Parses the ``[PLAN]`` block from the response
- Returns corrected actions + a human-readable ``learned_fact`` string

Usage::

    from .correction_agent import async_try_correct_failures

    correction = await async_try_correct_failures(hass, results, actions, plan_summary)
    if correction:
        # correction["corrected_actions"] — list of actions to re-execute
        # correction["message"]           — chat message for [🔧 CORRECTION] card
        # correction["learned_fact"]      — short string to show as toast
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_AZURE_API_KEY,
    CONF_AZURE_API_VERSION,
    CONF_AZURE_DEPLOYMENT,
    CONF_AZURE_ENDPOINT,
    CONF_OPENAI_API_KEY,
    CONF_OPENAI_BASE_URL,
    CONF_OPENAI_MODEL,
    CONF_ANTHROPIC_API_KEY,
    CONF_ANTHROPIC_MODEL,
    CONF_CLOUD_PROVIDER,
    CONF_CLOUD_USE_FOR_CHAT,
    DEFAULT_AZURE_API_VERSION,
    DEFAULT_CLOUD_PROVIDER,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_ANTHROPIC_MODEL,
    CLOUD_PROVIDER_AZURE,
    CLOUD_PROVIDER_OPENAI,
    CLOUD_PROVIDER_ANTHROPIC,
    DOMAIN,
)
from .domain_docs import DOMAIN_DOCS
from .response_processing import _extract_plan_block

_LOGGER = logging.getLogger(__name__)

_CORRECTION_TIMEOUT = 60  # seconds

_CORRECTION_SYSTEM_PROMPT = """\
You are a Home Assistant automation assistant. A plan action has failed.
Your ONLY job is to provide a corrected version of the failed actions.

Rules:
- Return ONLY a ```plan``` JSON block — no prose, no explanation
- Keep the same intent (same entities, same goal)
- Use the domain documentation provided to pick correct parameters
- If color is needed, prefer rgb_color over color_temp unless the entity supports color_temp

Plan format:
```plan
{{
  "summary": "<brief correction summary>",
  "actions": [
    {{
      "type": "call_service",
      "domain": "<domain>",
      "service": "<service>",
      "entity_id": "<entity_id>",
      "service_data": {{ ... }},
      "description": "<what this does>"
    }}
  ]
}}
```
"""


def _get_kyber_config(hass: HomeAssistant) -> dict[str, Any]:
    """Return the first Kyber config entry's data dict, or {}."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    return dict(entries[0].data or {})


def _build_correction_prompt(
    failed_actions: list[dict],
    original_actions: list[dict],
    plan_summary: str,
    errors: list[str],
) -> str:
    """Build the focused micro-prompt for the correction agent."""
    # Collect domains from failed actions
    domains: set[str] = set()
    for action in failed_actions:
        domain = action.get("domain", "")
        if not domain and action.get("entity_id", "").count(".") == 1:
            domain = action["entity_id"].split(".")[0]
        if domain:
            domains.add(domain)

    # Pre-load domain docs
    domain_context_parts: list[str] = []
    for domain in sorted(domains):
        doc = DOMAIN_DOCS.get(domain, "")
        if doc:
            domain_context_parts.append(f"### {domain} domain docs\n{doc}")
        else:
            domain_context_parts.append(
                f"### {domain} domain docs\nNo specific docs — use standard HA service names."
            )
    domain_context = "\n\n".join(domain_context_parts) or "No domain docs available."

    prompt = (
        f"Original plan summary: {plan_summary}\n\n"
        f"These actions FAILED:\n{json.dumps(failed_actions, indent=2)}\n\n"
        f"Errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
        f"All original actions (for context):\n{json.dumps(original_actions, indent=2)}\n\n"
        f"## Domain reference\n\n{domain_context}\n\n"
        "Provide a corrected plan that achieves the same goal."
    )
    return prompt


async def _make_ai_call(
    hass: HomeAssistant,
    instructions: str,
    provider_cfg: dict[str, Any],
) -> str:
    """Dispatch an AI call to the configured provider and return the response text.

    This is a thin wrapper that can be mocked in tests without needing to stub
    the full api_utilities module.  It raises ``asyncio.TimeoutError`` on timeout
    and any other exception from the underlying provider call on failure.
    """
    # Lazy import to avoid circular deps at module load time
    from .api_utilities import (  # noqa: PLC0415
        async_ai_call,
        async_azure_ai_call,
        async_openai_ai_call,
        async_anthropic_ai_call,
    )

    _use_azure = provider_cfg["use_azure"]
    _use_openai = provider_cfg["use_openai"]
    _use_anthropic = provider_cfg["use_anthropic"]

    if _use_azure:
        _LOGGER.info("Kyber correction: calling Azure provider")
        result = await asyncio.wait_for(
            async_azure_ai_call(
                task_name=f"{DOMAIN}_correction",
                endpoint=provider_cfg["azure_endpoint"],
                api_key=provider_cfg["azure_key"],
                deployment=provider_cfg["azure_deployment"],
                api_version=provider_cfg["azure_api_version"],
                instructions=instructions,
                history=[],
            ),
            timeout=_CORRECTION_TIMEOUT,
        )
    elif _use_openai:
        _LOGGER.info("Kyber correction: calling OpenAI provider")
        result = await asyncio.wait_for(
            async_openai_ai_call(
                task_name=f"{DOMAIN}_correction",
                api_key=provider_cfg["openai_key"],
                model=provider_cfg["openai_model"],
                base_url=provider_cfg["openai_base_url"] or None,
                instructions=instructions,
                history=[],
            ),
            timeout=_CORRECTION_TIMEOUT,
        )
    elif _use_anthropic:
        _LOGGER.info("Kyber correction: calling Anthropic provider")
        result = await asyncio.wait_for(
            async_anthropic_ai_call(
                task_name=f"{DOMAIN}_correction",
                api_key=provider_cfg["anthropic_key"],
                model=provider_cfg["anthropic_model"],
                instructions=instructions,
                history=[],
            ),
            timeout=_CORRECTION_TIMEOUT,
        )
    else:
        entity_id = provider_cfg["entity_id"]
        _LOGGER.info("Kyber correction: calling Ollama/local provider (entity=%s)", entity_id)
        result = await asyncio.wait_for(
            async_ai_call(
                hass,
                task_name=f"{DOMAIN}_correction",
                entity_id=entity_id,
                instructions=instructions,
            ),
            timeout=_CORRECTION_TIMEOUT,
        )

    return result.data if isinstance(result.data, str) else str(result.data or "")


async def async_try_correct_failures(
    hass: HomeAssistant,
    results: list[dict],
    original_actions: list[dict],
    plan_summary: str,
) -> dict[str, Any] | None:
    """Attempt to correct failed call_service actions using an AI micro-prompt.

    Returns a dict with keys:
    - ``corrected_actions``: list[dict] — the corrected plan actions
    - ``message``: str — human-readable correction summary for the chat
    - ``learned_fact``: str — short toast-friendly learning note

    Returns ``None`` if there are no correctable failures, or if the AI call
    fails, times out, or produces no valid plan block.
    """
    # Only correct call_service failures
    failed: list[dict] = [
        r for r in results
        if r.get("status") == "error" and
        any(
            a.get("type") == "call_service" and
            (a.get("entity_id", "") == r.get("entity_id", "") or
             a.get("domain", "") == (r.get("entity_id", "").split(".")[0] if "." in r.get("entity_id", "") else ""))
            for a in original_actions
        )
    ]

    if not failed:
        _LOGGER.debug("Kyber correction: no correctable call_service failures found")
        return None

    errors = [str(r.get("message", "unknown error")) for r in failed]
    failed_action_dicts = [
        a for a in original_actions
        if any(
            a.get("entity_id", "") == r.get("entity_id", "")
            for r in failed
        )
    ]
    if not failed_action_dicts:
        # Narrow fallback: match by domain of the failed entity_ids only
        failed_domains = {
            r.get("entity_id", "").split(".")[0]
            for r in failed
            if "." in r.get("entity_id", "")
        }
        failed_action_dicts = [
            a for a in original_actions
            if a.get("type") == "call_service"
            and (
                a.get("domain", "") in failed_domains
                or a.get("entity_id", "").split(".")[0] in failed_domains
            )
        ]

    _LOGGER.info(
        "Kyber correction: %d failed action(s) — triggering micro-prompt",
        len(failed),
    )

    cfg = _get_kyber_config(hass)
    entity_id = str(cfg.get(CONF_AI_TASK_ENTITY_ID, "")).strip()
    _cloud_provider = str(cfg.get(CONF_CLOUD_PROVIDER, DEFAULT_CLOUD_PROVIDER)).strip()
    _cloud_use = bool(cfg.get(CONF_CLOUD_USE_FOR_CHAT, False))
    _azure_endpoint = str(cfg.get(CONF_AZURE_ENDPOINT, "")).strip()
    _azure_key = str(cfg.get(CONF_AZURE_API_KEY, "")).strip()
    _azure_deployment = str(cfg.get(CONF_AZURE_DEPLOYMENT, "")).strip()
    _azure_api_version = str(cfg.get(CONF_AZURE_API_VERSION, DEFAULT_AZURE_API_VERSION)).strip() or DEFAULT_AZURE_API_VERSION
    _openai_key = str(cfg.get(CONF_OPENAI_API_KEY, "")).strip()
    _openai_model = str(cfg.get(CONF_OPENAI_MODEL, DEFAULT_OPENAI_MODEL)).strip() or DEFAULT_OPENAI_MODEL
    _openai_base_url = str(cfg.get(CONF_OPENAI_BASE_URL, "")).strip()
    _anthropic_key = str(cfg.get(CONF_ANTHROPIC_API_KEY, "")).strip()
    _anthropic_model = str(cfg.get(CONF_ANTHROPIC_MODEL, DEFAULT_ANTHROPIC_MODEL)).strip() or DEFAULT_ANTHROPIC_MODEL

    # Backward compat
    if _cloud_provider == DEFAULT_CLOUD_PROVIDER and _azure_endpoint and _azure_key and _azure_deployment:
        _cloud_provider = CLOUD_PROVIDER_AZURE
        _cloud_use = True

    _use_azure = _cloud_use and _cloud_provider == CLOUD_PROVIDER_AZURE and bool(_azure_endpoint and _azure_key and _azure_deployment)
    _use_openai = _cloud_use and _cloud_provider == CLOUD_PROVIDER_OPENAI and bool(_openai_key)
    _use_anthropic = _cloud_use and _cloud_provider == CLOUD_PROVIDER_ANTHROPIC and bool(_anthropic_key)

    if not _use_azure and not _use_openai and not _use_anthropic and not entity_id:
        _LOGGER.warning("Kyber correction: no AI provider configured — skipping")
        return None

    instructions = _CORRECTION_SYSTEM_PROMPT + "\n\n" + _build_correction_prompt(
        failed_action_dicts, original_actions, plan_summary, errors
    )

    provider_cfg = {
        "use_azure": _use_azure,
        "use_openai": _use_openai,
        "use_anthropic": _use_anthropic,
        "entity_id": entity_id,
        "azure_endpoint": _azure_endpoint,
        "azure_key": _azure_key,
        "azure_deployment": _azure_deployment,
        "azure_api_version": _azure_api_version,
        "openai_key": _openai_key,
        "openai_model": _openai_model,
        "openai_base_url": _openai_base_url,
        "anthropic_key": _anthropic_key,
        "anthropic_model": _anthropic_model,
    }

    try:
        response_text = await _make_ai_call(hass, instructions, provider_cfg)
    except asyncio.TimeoutError:
        _LOGGER.warning("Kyber correction: AI call timed out after %ds", _CORRECTION_TIMEOUT)
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Kyber correction: AI call failed: %s", err)
        return None
    if not response_text.strip():
        _LOGGER.warning("Kyber correction: AI returned empty response")
        return None

    plan_block = _extract_plan_block(response_text)
    if not plan_block or not plan_block.get("actions"):
        _LOGGER.warning("Kyber correction: no valid plan block in AI response")
        return None

    corrected_actions: list[dict] = plan_block["actions"]
    summary = plan_block.get("summary", "Corrected plan")

    # Build a learned fact about what was wrong and what the correction is
    _learned_parts: list[str] = []
    for err_msg in set(errors):
        if "extra keys not allowed" in err_msg:
            import re as _re
            bad_keys = _re.findall(r"extra keys not allowed @ data\['([^']+)'\]", err_msg)
            if bad_keys:
                _learned_parts.append(
                    f"HA rejected parameter(s) {', '.join(bad_keys)} — removed from retry"
                )
    domains_str = ", ".join(sorted({
        a.get("domain", a.get("entity_id", "?").split(".")[0])
        for a in failed_action_dicts
    }))
    learned_fact = (
        f"🧠 Learned: {domains_str} correction — {'; '.join(_learned_parts) or summary}"
    )

    _LOGGER.info(
        "Kyber correction: success — %d corrected action(s): %s",
        len(corrected_actions), summary,
    )

    return {
        "corrected_actions": corrected_actions,
        "message": f"[🔧 CORRECTION] {summary}",
        "learned_fact": learned_fact,
        "original_errors": errors,
    }
