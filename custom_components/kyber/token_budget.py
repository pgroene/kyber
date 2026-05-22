"""Persistent daily token budget tracking for Kyber."""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CLOUD_PROVIDER_ANTHROPIC,
    CLOUD_PROVIDER_AZURE,
    CLOUD_PROVIDER_NONE,
    CLOUD_PROVIDER_OPENAI,
    CONF_CLOUD_PROVIDER,
    CONF_CLOUD_USE_FOR_CHAT,
)

_STORAGE_VERSION = 1
_STORAGE_KEY = "kyber.token_budget"
_INSTANCE_KEY = "kyber_token_budget_store"
_LOCAL_PROVIDER = "home_assistant"


def get_budget_provider(config: Mapping[str, Any]) -> str:
    """Return the provider key used for token budget tracking."""
    provider = str(config.get(CONF_CLOUD_PROVIDER, CLOUD_PROVIDER_NONE) or CLOUD_PROVIDER_NONE).strip().lower()
    if bool(config.get(CONF_CLOUD_USE_FOR_CHAT, False)) and provider in {
        CLOUD_PROVIDER_AZURE,
        CLOUD_PROVIDER_OPENAI,
        CLOUD_PROVIDER_ANTHROPIC,
    }:
        return provider
    return _LOCAL_PROVIDER


class TokenBudgetStore:
    """Persist daily token usage, reset automatically at local midnight."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._data: dict[str, Any] = {"date": "", "providers": {}}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load token usage from storage once."""
        async with self._lock:
            if self._loaded:
                return
            loaded = await self._store.async_load()
            self._data = self._normalize_loaded(loaded)
            self._loaded = True
            if self._ensure_current_day():
                await self._store.async_save(self._data)

    async def async_get_usage(self, provider: str, budget: int = 0) -> dict[str, Any]:
        """Return the current usage snapshot for a provider."""
        await self.async_load()
        async with self._lock:
            changed = self._ensure_current_day()
            usage = self._build_usage(provider, budget)
            if changed:
                await self._store.async_save(self._data)
            return usage

    async def async_check(
        self,
        provider: str,
        budget: int,
        estimated_tokens: int = 0,
    ) -> tuple[bool, dict[str, Any]]:
        """Check whether another AI call is allowed for this provider."""
        await self.async_load()
        async with self._lock:
            changed = self._ensure_current_day()
            usage = self._build_usage(provider, budget)
            projected_used = usage["used"] + max(0, int(estimated_tokens or 0))
            usage["projected_used"] = projected_used
            usage["projected_pct"] = self._calculate_pct(projected_used, budget)
            allowed = budget <= 0 or projected_used < budget
            if changed:
                await self._store.async_save(self._data)
            return allowed, usage

    async def async_record(self, provider: str, tokens: int, budget: int = 0) -> dict[str, Any]:
        """Record used tokens for a provider and return the updated snapshot."""
        await self.async_load()
        async with self._lock:
            self._ensure_current_day()
            providers = self._data.setdefault("providers", {})
            provider_data = providers.setdefault(provider, {"used_tokens": 0})
            provider_data["used_tokens"] = int(provider_data.get("used_tokens", 0) or 0) + max(0, int(tokens or 0))
            await self._store.async_save(self._data)
            return self._build_usage(provider, budget)

    def _normalize_loaded(self, loaded: Any) -> dict[str, Any]:
        if not isinstance(loaded, dict):
            return {"date": self._today_key(), "providers": {}}
        providers = loaded.get("providers")
        if not isinstance(providers, dict):
            legacy_used = int(loaded.get("used_tokens", 0) or 0)
            providers = {_LOCAL_PROVIDER: {"used_tokens": legacy_used}} if legacy_used > 0 else {}
        normalized: dict[str, Any] = {"date": str(loaded.get("date") or self._today_key()), "providers": {}}
        for provider, data in providers.items():
            if not isinstance(data, dict):
                continue
            normalized["providers"][str(provider)] = {
                "used_tokens": max(0, int(data.get("used_tokens", 0) or 0))
            }
        return normalized

    def _today_key(self) -> str:
        return dt_util.now().date().isoformat()

    def _ensure_current_day(self) -> bool:
        today = self._today_key()
        if self._data.get("date") == today:
            return False
        self._data = {"date": today, "providers": {}}
        return True

    def _build_usage(self, provider: str, budget: int) -> dict[str, Any]:
        provider_key = str(provider or _LOCAL_PROVIDER)
        provider_data = self._data.get("providers", {}).get(provider_key, {})
        used = max(0, int(provider_data.get("used_tokens", 0) or 0))
        budget_int = max(0, int(budget or 0))
        pct = self._calculate_pct(used, budget_int)
        return {
            "date": self._data.get("date") or self._today_key(),
            "provider": provider_key,
            "used": used,
            "budget": budget_int,
            "remaining": max(budget_int - used, 0) if budget_int > 0 else None,
            "pct": pct,
            "warning": budget_int > 0 and pct >= 80,
            "exceeded": budget_int > 0 and used >= budget_int,
        }

    @staticmethod
    def _calculate_pct(used: int, budget: int) -> int:
        if budget <= 0:
            return 0
        return int(round((max(0, used) / budget) * 100))


def get_store(hass: HomeAssistant) -> TokenBudgetStore:
    """Return the shared token budget store instance."""
    store = hass.data.get(_INSTANCE_KEY)
    if store is None or store.hass is not hass:
        store = TokenBudgetStore(hass)
        hass.data[_INSTANCE_KEY] = store
    return store
