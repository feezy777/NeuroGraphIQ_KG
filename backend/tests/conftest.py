"""Shared pytest fixtures — isolate tests from developer-local .env LLM keys."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_llm_env_api_keys(monkeypatch):
    """Tests must not inherit DeepSeek/Kimi keys from backend/.env unless they override."""
    from app.config import get_settings

    settings = get_settings()
    empty_keys = settings.model_copy(update={"deepseek_api_key": "", "kimi_api_key": ""})
    monkeypatch.setattr("app.config.get_settings", lambda: empty_keys)
    monkeypatch.setattr("app.services.settings_service.get_settings", lambda: empty_keys)
