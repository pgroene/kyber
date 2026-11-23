"""Gate Kyber's HTTP views on the state of the config entry.

aiohttp cannot remove a route once it is added, so Kyber registers its views
once per HA run. Without a gate they would keep answering after the entry is
unloaded or deleted, and /api/kyber/mcp would keep serving its tools after MCP
was switched off. Each handler is wrapped so it checks at request time:

- no entry loaded (``kyber_config`` missing from hass.data) → 503
- MCP views while ``enable_mcp`` is off → 404
"""
from __future__ import annotations

import functools
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from .const import CONF_ENABLE_MCP, DEFAULT_ENABLE_MCP

if TYPE_CHECKING:
    from aiohttp import web
    from homeassistant.helpers.http import HomeAssistantView

CONFIG_KEY = "kyber_config"
_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def kyber_loaded(hass: Any) -> bool:
    """True while a Kyber config entry is set up."""
    return CONFIG_KEY in hass.data


def mcp_enabled(config: dict[str, Any]) -> bool:
    """Effective enable_mcp setting from the merged data+options config."""
    return bool(config.get(CONF_ENABLE_MCP, DEFAULT_ENABLE_MCP))


def gate_view(view: "HomeAssistantView", *, mcp: bool = False) -> "HomeAssistantView":
    """Wrap every HTTP handler of ``view`` in the load (and MCP) check."""
    for method in _HTTP_METHODS:
        handler = getattr(view, method, None)
        if handler is None:
            continue
        setattr(view, method, _gated(view, handler, mcp=mcp))
    return view


def _gated(view: "HomeAssistantView", handler: Any, *, mcp: bool) -> Any:
    @functools.wraps(handler)
    async def _handler(request: "web.Request", *args: Any, **kwargs: Any) -> Any:
        hass = request.app["hass"]
        config = hass.data.get(CONFIG_KEY)
        if config is None:
            return view.json_message(
                "Kyber is not loaded", HTTPStatus.SERVICE_UNAVAILABLE
            )
        if mcp and not mcp_enabled(config):
            return view.json_message("MCP is disabled", HTTPStatus.NOT_FOUND)
        return await handler(request, *args, **kwargs)

    return _handler
