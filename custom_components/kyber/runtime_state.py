"""Persistent runtime state that does not belong in the config entry.

Last-run timestamps of the narrator and deep learning, and the version of the
initial learning pass, used to live in ``entry.data``. Every write there fires
the config entry's update listeners, which reloaded the whole integration and
cancelled the learning it had just finished. They now live in their own Store
(``.storage/kyber_runtime``); values found in ``entry.data`` are moved over
once during setup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .const import (
    CONF_DEEP_LEARNING_LAST_RUN_TS,
    CONF_INITIAL_LEARNING_DONE,
    CONF_INITIAL_LEARNING_VERSION,
    CONF_NARRATOR_LAST_RUN_TS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_STORE_KEY = "kyber_runtime"
_STORE_VERSION = 1
RUNTIME_STATE_KEY = "kyber_runtime_state"

# Keys that older versions wrote into entry.data at runtime.
LEGACY_ENTRY_DATA_KEYS: tuple[str, ...] = (
    CONF_NARRATOR_LAST_RUN_TS,
    CONF_DEEP_LEARNING_LAST_RUN_TS,
    CONF_INITIAL_LEARNING_VERSION,
    CONF_INITIAL_LEARNING_DONE,
)


class RuntimeState:
    """Small key/value store for runtime bookkeeping."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self._store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
        self._data: dict[str, Any] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self._data = dict(data) if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    async def async_set(self, key: str, value: Any) -> None:
        self._data[key] = value
        await self._store.async_save(dict(self._data))

    async def async_adopt_legacy(self, legacy: dict[str, Any]) -> None:
        """Take over values from entry.data without overwriting newer ones."""
        for key, value in legacy.items():
            self._data.setdefault(key, value)
        await self._store.async_save(dict(self._data))


async def async_setup_runtime_state(
    hass: "HomeAssistant", entry: "ConfigEntry"
) -> RuntimeState:
    """Load the runtime state and move legacy values out of entry.data.

    Must run before the update listener is registered: the clean-up of
    entry.data is itself a config entry update.
    """
    state = RuntimeState(hass)
    await state.async_load()
    legacy = {k: entry.data[k] for k in LEGACY_ENTRY_DATA_KEYS if k in entry.data}
    if legacy:
        await state.async_adopt_legacy(legacy)
        hass.config_entries.async_update_entry(
            entry,
            data={k: v for k, v in entry.data.items() if k not in LEGACY_ENTRY_DATA_KEYS},
        )
    hass.data[RUNTIME_STATE_KEY] = state
    return state


def get_runtime_state(hass: "HomeAssistant") -> RuntimeState:
    """Return the runtime state loaded during setup."""
    return hass.data[RUNTIME_STATE_KEY]
