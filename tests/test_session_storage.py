"""Unit tests for session and storage helpers in http_api.py.

Covers:
  - _new_session_id
  - _migrate_user_to_sessions
  - _get_active_session
  - _sanitize_history
  - _sanitize_summary
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ── HA + aiohttp stubs ────────────────────────────────────────────────────────
_STUBS = [
    "homeassistant", "homeassistant.core", "homeassistant.components",
    "homeassistant.components.http", "homeassistant.helpers",
    "homeassistant.helpers.storage", "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry",
    "homeassistant.helpers.label_registry", "homeassistant.helpers.template",
    "homeassistant.const", "homeassistant.exceptions",
    "homeassistant.util", "homeassistant.util.dt",
    "homeassistant.config", "homeassistant.loader",
    "aiohttp", "aiohttp.web",
]
for _m in _STUBS:
    sys.modules.setdefault(_m, types.ModuleType(_m))
sys.modules["aiohttp"].web = types.ModuleType("aiohttp.web")


class _Stub:
    pass


sys.modules["homeassistant.components.http"].HomeAssistantView = _Stub
sys.modules["homeassistant.core"].HomeAssistant = _Stub
sys.modules["homeassistant.core"].callback = lambda f: f
sys.modules["homeassistant.helpers.storage"].Store = _Stub
sys.modules["homeassistant.exceptions"].HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules["homeassistant.helpers"].area_registry = sys.modules["homeassistant.helpers.area_registry"]
sys.modules["homeassistant.helpers"].entity_registry = sys.modules["homeassistant.helpers.entity_registry"]
sys.modules["homeassistant.helpers"].label_registry = sys.modules["homeassistant.helpers.label_registry"]
sys.modules["homeassistant.helpers"].device_registry = sys.modules["homeassistant.helpers.device_registry"]
for _r in ("entity_registry", "area_registry", "device_registry", "label_registry"):
    sys.modules[f"homeassistant.helpers.{_r}"].async_get = lambda *a, **k: None
sys.modules.setdefault("homeassistant.components.ai_task", types.ModuleType("homeassistant.components.ai_task"))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", _pkg_cc)

_pkg_kyber = types.ModuleType("custom_components.kyber")
_pkg_kyber.__path__ = [str(ROOT / "custom_components" / "kyber")]
sys.modules["custom_components.kyber"] = _pkg_kyber


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.kyber.const", ROOT / "custom_components" / "kyber" / "const.py")
_load("custom_components.kyber.knowledge", ROOT / "custom_components" / "kyber" / "knowledge.py")
_load("custom_components.kyber.analyzer", ROOT / "custom_components" / "kyber" / "analyzer.py")
http_api = _load("custom_components.kyber.http_api", ROOT / "custom_components" / "kyber" / "http_api.py")

_new_session_id = http_api._new_session_id
_migrate_user_to_sessions = http_api._migrate_user_to_sessions
_get_active_session = http_api._get_active_session
_sanitize_history = http_api._sanitize_history
_sanitize_summary = http_api._sanitize_summary


# ── _new_session_id ───────────────────────────────────────────────────────────

class TestNewSessionId:
    def test_returns_string(self):
        sid = _new_session_id()
        assert isinstance(sid, str)

    def test_non_empty(self):
        assert len(_new_session_id()) > 0

    def test_unique(self):
        ids = {_new_session_id() for _ in range(20)}
        assert len(ids) == 20, "Expected all unique session IDs"

    def test_alphanumeric(self):
        sid = _new_session_id()
        assert sid.isalnum(), f"Expected alphanumeric, got: {sid!r}"


# ── _migrate_user_to_sessions ─────────────────────────────────────────────────

class TestMigrateUserToSessions:
    def test_already_migrated_unchanged(self):
        data = {"sessions": {"abc": {"name": "S1", "history": []}}, "active_session": "abc"}
        result = _migrate_user_to_sessions(data)
        assert result is data

    def test_migrates_old_format(self):
        old = {
            "history": [{"role": "user", "content": "hi"}],
            "compacted_summary": "previous context",
        }
        result = _migrate_user_to_sessions(old)
        assert "sessions" in result
        assert "active_session" in result
        sid = result["active_session"]
        session = result["sessions"][sid]
        assert session["history"] == [{"role": "user", "content": "hi"}]
        assert session["compacted_summary"] == "previous context"
        assert session["name"] == "Session 1"

    def test_empty_old_format(self):
        result = _migrate_user_to_sessions({})
        assert "sessions" in result
        sid = result["active_session"]
        assert result["sessions"][sid]["history"] == []
        assert result["sessions"][sid]["compacted_summary"] == ""


# ── _get_active_session ───────────────────────────────────────────────────────

class TestGetActiveSession:
    def test_returns_active_session(self):
        sid = "abc123"
        session_data = {"name": "Test", "history": [], "compacted_summary": ""}
        user_data = {"sessions": {sid: session_data}, "active_session": sid}
        got_sid, got_session = _get_active_session(user_data)
        assert got_sid == sid
        assert got_session is session_data

    def test_falls_back_to_first_session_when_active_missing(self):
        sid = "abc123"
        session_data = {"name": "Test", "history": []}
        user_data = {"sessions": {sid: session_data}, "active_session": "nonexistent"}
        got_sid, got_session = _get_active_session(user_data)
        assert got_sid == sid
        assert got_session is session_data
        assert user_data["active_session"] == sid

    def test_creates_new_session_when_empty(self):
        user_data: dict = {}
        got_sid, got_session = _get_active_session(user_data)
        assert got_sid
        assert got_session["name"] == "Session 1"
        assert got_session["history"] == []
        assert user_data["active_session"] == got_sid
        assert got_sid in user_data["sessions"]


# ── _sanitize_history ─────────────────────────────────────────────────────────

class TestSanitizeHistory:
    def test_empty_list(self):
        assert _sanitize_history([]) == []

    def test_non_list_returns_empty(self):
        assert _sanitize_history(None) == []
        assert _sanitize_history("not a list") == []
        assert _sanitize_history(42) == []

    def test_filters_empty_content(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "   "},
        ]
        result = _sanitize_history(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "hello"

    def test_normalizes_roles(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "system", "content": "unexpected"},  # non-user → assistant
        ]
        result = _sanitize_history(msgs)
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "assistant"

    def test_truncates_long_messages(self):
        long_content = "x" * 100_000
        msgs = [{"role": "user", "content": long_content}]
        result = _sanitize_history(msgs)
        assert len(result[0]["content"]) < 100_000

    def test_keeps_last_n_messages(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(300)]
        result = _sanitize_history(msgs)
        # Should be bounded — not all 300
        assert len(result) <= 200
        # Should keep the last messages
        assert result[-1]["content"] == "msg299"

    def test_skips_non_dict_items(self):
        msgs = [{"role": "user", "content": "hi"}, "not a dict", 42, None]
        result = _sanitize_history(msgs)
        assert len(result) == 1


# ── _sanitize_summary ─────────────────────────────────────────────────────────

class TestSanitizeSummary:
    def test_returns_string(self):
        assert isinstance(_sanitize_summary("hello"), str)

    def test_none_returns_empty(self):
        assert _sanitize_summary(None) == ""

    def test_strips_whitespace(self):
        assert _sanitize_summary("  hello  ") == "hello"

    def test_truncates_long_summary(self):
        long = "x" * 1_000_000
        result = _sanitize_summary(long)
        assert len(result) < 1_000_000
