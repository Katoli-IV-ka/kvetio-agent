"""Tests for bot/routine.py — /fire routine trigger client."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.config import RunConfig
from bot.routine import config_to_text, fire


# ── config_to_text ────────────────────────────────────────────────────────────

class TestConfigToText:
    def _cfg(self, **kwargs) -> RunConfig:
        defaults = dict(segments=["medical-imaging"], limit_per_segment=5, stages="full")
        defaults.update(kwargs)
        return RunConfig(**defaults)

    def test_full_stages(self) -> None:
        text = config_to_text(self._cfg())
        assert "segments=medical-imaging" in text
        assert "limit=5" in text
        assert "stages=full" in text

    def test_partial_stages(self) -> None:
        text = config_to_text(self._cfg(stages=["discovery", "relevance"]))
        assert "stages=discovery,relevance" in text

    def test_multiple_segments(self) -> None:
        text = config_to_text(self._cfg(segments=["medical-imaging", "robotics-ai"]))
        assert "segments=medical-imaging,robotics-ai" in text

    def test_dry_run_flag(self) -> None:
        assert "dry_run=true" in config_to_text(self._cfg(dry_run=True))
        assert "dry_run=false" in config_to_text(self._cfg(dry_run=False))

    def test_notion_sync_flag(self) -> None:
        assert "notion_sync=false" in config_to_text(self._cfg(notion_sync=False))

    def test_from_dict_defaults_limit_to_five(self) -> None:
        cfg = RunConfig.from_dict({"segments": ["medical-imaging"]})
        assert cfg.limit_per_segment == 5
        assert "limit=5" in config_to_text(cfg)


# ── fire() ────────────────────────────────────────────────────────────────────

class TestFire:
    def test_dev_mode_when_no_env_vars(self, monkeypatch) -> None:
        monkeypatch.delenv("ROUTINE_FIRE_URL", raising=False)
        monkeypatch.delenv("ROUTINE_TOKEN", raising=False)
        result = fire("hello")
        assert result["dev_mode"] is True
        assert result["text"] == "hello"

    def test_sends_correct_headers(self, monkeypatch) -> None:
        monkeypatch.setenv("ROUTINE_FIRE_URL", "https://example.com/fire")
        monkeypatch.setenv("ROUTINE_TOKEN", "test-token")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"claude_code_session_id": "sess-123"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            fire("segments=medical-imaging; limit=5")

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["anthropic-beta"] == "experimental-cc-routine-2026-04-01"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_strips_common_env_copy_paste_wrappers(self, monkeypatch) -> None:
        monkeypatch.setenv("ROUTINE_FIRE_URL", "  https://example.com/fire  ")
        monkeypatch.setenv("ROUTINE_TOKEN", ' "test-token" ')

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"claude_code_session_id": "sess-123"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            fire("segments=medical-imaging; limit=5")

        call_kwargs = mock_client.post.call_args
        assert call_kwargs.args[0] == "https://example.com/fire"
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-token"

    def test_sends_correct_body(self, monkeypatch) -> None:
        monkeypatch.setenv("ROUTINE_FIRE_URL", "https://example.com/fire")
        monkeypatch.setenv("ROUTINE_TOKEN", "test-token")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"claude_code_session_id": "sess-xyz"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            fire("my text payload")

        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"] == {"text": "my text payload"}

    def test_returns_parsed_response(self, monkeypatch) -> None:
        monkeypatch.setenv("ROUTINE_FIRE_URL", "https://example.com/fire")
        monkeypatch.setenv("ROUTINE_TOKEN", "tok")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"claude_code_session_id": "abc"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            result = fire("x")

        assert result["claude_code_session_id"] == "abc"

    def test_http_error_returns_error_dict(self, monkeypatch) -> None:
        import httpx as _httpx

        monkeypatch.setenv("ROUTINE_FIRE_URL", "https://example.com/fire")
        monkeypatch.setenv("ROUTINE_TOKEN", "tok")

        err_response = MagicMock()
        err_response.status_code = 403
        err_response.text = "Forbidden"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = _httpx.HTTPStatusError(
            "403", request=MagicMock(), response=err_response
        )

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            result = fire("x")

        assert "error" in result
        assert "403" in result["error"]

    def test_auth_error_returns_actionable_hint(self, monkeypatch) -> None:
        import httpx as _httpx

        monkeypatch.setenv("ROUTINE_FIRE_URL", "https://example.com/fire")
        monkeypatch.setenv("ROUTINE_TOKEN", "bad-token")

        err_response = MagicMock()
        err_response.status_code = 401
        err_response.text = '{"type":"error","error":{"type":"authentication_error"}}'

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = _httpx.HTTPStatusError(
            "401", request=MagicMock(), response=err_response
        )

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            result = fire("x")

        assert result["error"] == "HTTP 401: ROUTINE_TOKEN rejected by Anthropic"
        assert "Regenerate the API trigger token" in result["hint"]

    def test_network_error_returns_error_dict(self, monkeypatch) -> None:
        monkeypatch.setenv("ROUTINE_FIRE_URL", "https://example.com/fire")
        monkeypatch.setenv("ROUTINE_TOKEN", "tok")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = ConnectionError("network down")

        with patch("bot.routine.httpx.Client", return_value=mock_client):
            result = fire("x")

        assert "error" in result
        assert "network down" in result["error"]
