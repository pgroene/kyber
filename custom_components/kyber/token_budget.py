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


class TokenReservation:
    """Tokens reserved by ``TokenBudgetStore.async_reserve``, settled exactly once.

    Either ``async_settle`` books the real usage, or ``release`` drops the
    reservation (error, abort). Both are no-ops once one of them ran.
    """

    def __init__(
        self, store: TokenBudgetStore, provider: str, budget: int, estimated_tokens: int, reserved_on: str | None
    ) -> None:
        self._store = store
        self._provider = provider
        self._budget = budget
        self._estimated = estimated_tokens
        self._reserved_on = reserved_on
        self._open = True

    async def async_settle(self, tokens: int) -> dict[str, Any] | None:
        """Record ``tokens`` as used and release the reservation."""
        if not self._open:
            return None
        self._open = False
        # Shielded: once handed over, the booking finishes even if the caller
        # is cancelled now, so the reservation is released exactly once.
        return await asyncio.shield(self._store.async_record(
            self._provider, tokens, self._budget,
            estimated_tokens=self._estimated, reserved_on=self._reserved_on,
        ))

    def release(self) -> None:
        """Drop the reservation without recording usage (synchronous, safe in ``finally``)."""
        if not self._open:
            return
        self._open = False
        self._store.release_reservation(self._provider, self._estimated, self._reserved_on)


class TokenBudgetStore:
    """Persist daily token usage, reset automatically at local midnight."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._data: dict[str, Any] = {"date": "", "providers": {}}
        self._loaded = False
        self._lock = asyncio.Lock()
        # In-memory reservation counter for in-flight AI calls.
        # Not persisted — only lives for the duration of the request.
        self._pending: dict[str, int] = {}

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
        """Check whether another AI call is allowed and reserve the estimated tokens.

        Uses an in-memory ``_pending`` counter so concurrent requests see updated
        projected usage without touching persisted storage (which is only updated
        when tokens are actually recorded in ``async_record``).
        """
        await self.async_load()
        async with self._lock:
            if self._ensure_current_day():
                await self._store.async_save(self._data)
            usage = self._build_usage(provider, budget)
            est = max(0, int(estimated_tokens or 0))
            pending = self._pending.get(provider, 0)
            projected_used = usage["used"] + pending + est
            usage["projected_used"] = projected_used
            usage["projected_pct"] = self._calculate_pct(projected_used, budget)
            allowed = budget <= 0 or projected_used < budget
            if allowed and est > 0:
                # Reserve in-memory so concurrent requests see updated projected usage.
                # No await follows, so a caller that gets ``allowed`` back owns
                # exactly this reservation and must release it.
                self._pending[provider] = pending + est
            return allowed, usage

    async def async_reserve(
        self,
        provider: str,
        budget: int,
        estimated_tokens: int,
    ) -> tuple[TokenReservation | None, dict[str, Any]]:
        """Check the budget like ``async_check``; return a reservation when allowed.

        The caller must settle or release the reservation on every exit.
        """
        allowed, usage = await self.async_check(provider, budget, estimated_tokens)
        if not allowed:
            return None, usage
        return TokenReservation(self, provider, budget, estimated_tokens, usage.get("date")), usage

    def release_reservation(
        self, provider: str, estimated_tokens: int, reserved_on: str | None = None
    ) -> None:
        """Drop a reservation from ``async_check`` without recording usage.

        ``reserved_on`` is the ``date`` of the usage ``async_check`` returned;
        a reservation from before midnight is already gone with the old day.
        Synchronous, so it also runs in a ``finally`` of a cancelled request.
        """
        if reserved_on is not None and reserved_on != self._data.get("date"):
            return
        est = max(0, int(estimated_tokens or 0))
        if est > 0:
            self._pending[provider] = max(0, self._pending.get(provider, 0) - est)

    async def async_record(
        self,
        provider: str,
        tokens: int,
        budget: int = 0,
        estimated_tokens: int = 0,
        reserved_on: str | None = None,
    ) -> dict[str, Any]:
        """Record actual token usage and release any in-memory reservation.

        ``estimated_tokens`` and ``reserved_on`` describe the reservation from
        ``async_check`` (see ``release_reservation``). For failed calls use
        ``release_reservation`` instead of recording zero tokens.
        """
        await self.async_load()
        async with self._lock:
            self._ensure_current_day()
            self.release_reservation(provider, estimated_tokens, reserved_on)
            # Record actual tokens in persistent storage.
            actual = max(0, int(tokens or 0))
            if actual > 0:
                providers = self._data.setdefault("providers", {})
                provider_data = providers.setdefault(provider, {"used_tokens": 0})
                provider_data["used_tokens"] = int(provider_data.get("used_tokens", 0) or 0) + actual
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
        # Reservations belong to the day that made them; requests spanning
        # midnight pass ``reserved_on`` so their release skips the new day.
        self._pending = {}
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
