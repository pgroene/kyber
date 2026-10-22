"""Service descriptions for tests, read from Home Assistant's own services.yaml files.

``homeassistant.helpers.service.async_get_all_descriptions`` imports the
conversation integration, which needs ``hassil``; the test environment does
not have it, a real Home Assistant always does. The descriptions themselves
come from each integration's services.yaml, so tests read those directly.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml
from homeassistant import components


def descriptions(domains) -> dict[str, dict]:
    """``{domain: {service: description}}`` for the given integrations."""
    out: dict[str, dict] = {}
    for domain in domains:
        path = Path(components.__file__).parent / domain / "services.yaml"
        if path.exists():
            out[domain] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return out


@contextmanager
def described(domains):
    """Let async_get_all_descriptions answer for ``domains`` from their services.yaml."""
    with patch("homeassistant.helpers.service.async_get_all_descriptions",
               new=AsyncMock(return_value=descriptions(domains))):
        yield
