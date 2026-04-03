from __future__ import annotations

from scripts.desktop.services.action_help_service import ActionHelpService


def test_action_help_falls_back_without_key() -> None:
    service = ActionHelpService(
        runtime_provider=lambda: {
            "pipeline": {"use_deepseek": True},
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
        }
    )
    vm = service.get_help("import_files", {"has_active_ontology": True})
    assert vm["action_id"] == "import_files"
    assert vm["source"] in {"local_template", "local_fallback"}
    assert isinstance(vm["preconditions"], list)
    assert isinstance(vm["next_steps"], list)
