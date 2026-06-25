"""Workbench Settings Module tests (no PostgreSQL required)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def test_runtime_settings_defaults_do_not_expose_api_key(tmp_path, monkeypatch):
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )

    runtime = settings_service.load_runtime_settings()
    assert runtime.api_providers.deepseek.enabled is True
    assert runtime.api_providers.deepseek.default_model == "deepseek-chat"

    public = settings_service.to_public_runtime_settings(runtime)
    deepseek = public.api_providers.deepseek
    assert deepseek.api_key_configured is False
    assert deepseek.api_key_masked is None
    assert not hasattr(deepseek, "api_key")
    assert '"api_key":' not in public.model_dump_json()


def test_runtime_settings_masks_saved_api_key(tmp_path, monkeypatch):
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )

    updated = settings_service.update_runtime_settings(
        {
            "api_providers": {
                "deepseek": {
                    "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
                    "base_url": "https://api.deepseek.com/v1",
                    "default_model": "deepseek-chat",
                }
            }
        }
    )

    assert updated.api_providers.deepseek.api_key_configured is True
    assert updated.api_providers.deepseek.api_key_masked == "sk-****wxyz"
    assert "abcdefghijklmnopqrstuvwxyz" not in updated.model_dump_json()

    saved = json.loads(settings_service.RUNTIME_SETTINGS_PATH.read_text("utf-8"))
    assert saved["api_providers"]["deepseek"]["api_key"] == "sk-abcdefghijklmnopqrstuvwxyz"


def test_empty_api_key_does_not_overwrite_existing_key(tmp_path, monkeypatch):
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )

    settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"api_key": "sk-existing-value-1234"}}}
    )
    public = settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"api_key": ""}}}
    )

    assert public.api_providers.deepseek.api_key_configured is True
    saved = json.loads(settings_service.RUNTIME_SETTINGS_PATH.read_text("utf-8"))
    assert saved["api_providers"]["deepseek"]["api_key"] == "sk-existing-value-1234"


def test_explicit_clear_api_key_removes_saved_key(tmp_path, monkeypatch):
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )

    settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"api_key": "sk-existing-value-1234"}}}
    )
    public = settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"explicit_clear_api_key": True}}}
    )

    assert public.api_providers.deepseek.api_key_configured is False
    saved = json.loads(settings_service.RUNTIME_SETTINGS_PATH.read_text("utf-8"))
    assert saved["api_providers"]["deepseek"].get("api_key", "") == ""


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"api_providers": {"deepseek": {"max_batch_size": 21}}}, "max_batch_size"),
        ({"api_providers": {"deepseek": {"timeout_seconds": 4}}}, "timeout_seconds"),
        ({"api_providers": {"deepseek": {"timeout_seconds": 121}}}, "timeout_seconds"),
        ({"basic": {"default_page_size": 9}}, "default_page_size"),
        ({"basic": {"max_page_size": 501}}, "max_page_size"),
    ],
)
def test_runtime_settings_validation_limits(tmp_path, monkeypatch, payload, expected):
    from pydantic import ValidationError

    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )

    with pytest.raises(ValidationError) as excinfo:
        settings_service.update_runtime_settings(payload)
    assert expected in str(excinfo.value)


def test_settings_options_endpoint_does_not_return_api_key():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/settings/options")

    assert resp.status_code == 200
    body = resp.json()
    assert {"value": "zh-CN", "label": "中文"} in body["languages"]
    assert "deepseek-chat" in body["default_models"]["deepseek"]
    assert "api_key" not in json.dumps(body).lower()


def test_settings_runtime_endpoint_does_not_return_api_key(tmp_path, monkeypatch):
    from app.main import app
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )
    settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"api_key": "sk-existing-value-1234"}}}
    )

    client = TestClient(app)
    resp = client.get("/api/settings/runtime")

    assert resp.status_code == 200
    body_text = json.dumps(resp.json())
    assert "sk-existing-value-1234" not in body_text
    assert resp.json()["api_providers"]["deepseek"]["api_key_configured"] is True
    assert "api_key" not in resp.json()["api_providers"]["deepseek"]


def test_patch_runtime_endpoint_preserves_existing_key_on_empty_input(tmp_path, monkeypatch):
    from app.main import app
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )
    settings_service.update_runtime_settings(
        {"api_providers": {"deepseek": {"api_key": "sk-existing-value-1234"}}}
    )

    client = TestClient(app)
    resp = client.patch(
        "/api/settings/runtime",
        json={"api_providers": {"deepseek": {"api_key": ""}}},
    )

    assert resp.status_code == 200
    assert resp.json()["api_providers"]["deepseek"]["api_key_configured"] is True
    saved = json.loads(settings_service.RUNTIME_SETTINGS_PATH.read_text("utf-8"))
    assert saved["api_providers"]["deepseek"]["api_key"] == "sk-existing-value-1234"


def test_deepseek_test_endpoint_returns_clear_error_when_key_missing(tmp_path, monkeypatch):
    from app.main import app
    from app.services import settings_service

    monkeypatch.setattr(
        settings_service, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.local.json"
    )
    monkeypatch.setattr(
        settings_service,
        "get_deepseek_runtime_config",
        lambda: settings_service.DeepSeekRuntimeConfig(
            enabled=True,
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
            api_key="",
            timeout_seconds=30,
            max_batch_size=20,
        ),
    )

    client = TestClient(app)
    resp = client.post("/api/settings/api-providers/deepseek/test", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["provider"] == "deepseek"
    assert body["error_message"] == "DeepSeek API key is not configured."
