from __future__ import annotations

import json
from typing import Any, Callable

from scripts.desktop.models import ActionHelpViewModel
from scripts.utils.deepseek_client import DeepSeekClient


ActionTemplate = dict[str, Any]


ACTION_HELP_TEMPLATES: dict[str, ActionTemplate] = {
    "import_ontology": {
        "title": "Import Ontology",
        "purpose": "Import RDF/OWL/XML ontology and build runtime rule baseline.",
        "preconditions": ["Prepare a readable ontology file path."],
        "inputs": ["*.rdf / *.owl / *.xml"],
        "risks": ["Invalid ontology format can block gate.", "If import fails, preprocess and preview are disabled."],
        "next_steps": ["Check ontology version and class/relation stats.", "Then import source files."],
    },
    "import_files": {
        "title": "Import Files",
        "purpose": "Import structured or document files into file center.",
        "preconditions": ["Ontology import is recommended first."],
        "inputs": ["xlsx/csv/tsv/json/jsonl/txt/md/pdf/docx/rdf/owl/xml"],
        "risks": ["Without ontology, files can be uploaded but preprocess will not auto-run."],
        "next_steps": ["Select a file and check preview/report.", "Run preprocess."],
    },
    "start_preprocess": {
        "title": "Start Preprocess",
        "purpose": "Run parse -> normalize -> local checks -> DeepSeek checks -> auto fix.",
        "preconditions": ["Ontology gate must pass.", "At least one file must exist."],
        "inputs": ["Selected file or all files."],
        "risks": ["If DeepSeek is unavailable, fallback to local rules.", "Failed file remains in failed state."],
        "next_steps": ["Review report issues and fix plan.", "Then open extract."],
    },
    "show_report": {
        "title": "View Report",
        "purpose": "Show preprocess summary, issues, and action plan for selected file.",
        "preconditions": ["A file is selected."],
        "inputs": ["Report linked by file_id."],
        "risks": ["If file is unprocessed, report can be minimal."],
        "next_steps": ["Address WARN/FAIL first.", "Then run extract or load."],
    },
    "enter_extract": {
        "title": "Open Extract",
        "purpose": "Open major preview results including circuits, connections, crosscheck, and coverage.",
        "preconditions": ["At least one successful major preview run exists."],
        "inputs": ["Latest successful run artifacts."],
        "risks": ["Without successful run, extract panel stays empty."],
        "next_steps": ["Focus on Traversal Report and Uncovered Regions."],
    },
    "preview_refresh": {
        "title": "Refresh Preview",
        "purpose": "Refresh preview content for currently selected file.",
        "preconditions": ["A file is selected."],
        "inputs": ["Current file and page parameters."],
        "risks": ["Very large files can be slower to refresh."],
        "next_steps": ["Lower page size if preview is slow."],
    },
    "fine_route": {
        "title": "Fine Route",
        "purpose": "Get fine-processing route and I/O contract based on file type.",
        "preconditions": ["A file is selected.", "Fine-process gate must pass."],
        "inputs": ["Current file record."],
        "risks": ["Current route is placeholder and does not run real algorithm."],
        "next_steps": ["Implement target processor using route contracts."],
    },
    "save_settings": {
        "title": "Save Settings",
        "purpose": "Persist runtime settings for DB, DeepSeek, and input paths.",
        "preconditions": ["Settings values should be valid."],
        "inputs": ["runtime.local.yaml values."],
        "risks": ["Invalid values can break following actions."],
        "next_steps": ["Re-run import/preprocess to verify settings."],
    },
    "default": {
        "title": "Action Help",
        "purpose": "Explain action purpose, preconditions, and risks.",
        "preconditions": [],
        "inputs": [],
        "risks": [],
        "next_steps": [],
    },
}


class ActionHelpService:
    def __init__(
        self,
        runtime_provider: Callable[[], dict[str, Any]],
        log_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._runtime_provider = runtime_provider
        self._log_handler = log_handler
        self._cache: dict[str, dict[str, Any]] = {}

    def get_help(self, action_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context_payload = context or {}
        template = ACTION_HELP_TEMPLATES.get(action_id, ACTION_HELP_TEMPLATES["default"])
        cache_key = f"{action_id}|{json.dumps(context_payload, ensure_ascii=False, sort_keys=True)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        base = ActionHelpViewModel(
            action_id=action_id,
            title=str(template.get("title") or action_id),
            source="local_template",
            purpose=str(template.get("purpose") or ""),
            preconditions=[str(x) for x in template.get("preconditions", [])],
            inputs=[str(x) for x in template.get("inputs", [])],
            risks=[str(x) for x in template.get("risks", [])],
            next_steps=[str(x) for x in template.get("next_steps", [])],
            context_snapshot=context_payload,
        ).to_dict()

        runtime = self._runtime_provider() or {}
        pipeline_cfg = runtime.get("pipeline", {}) or {}
        deepseek_cfg = runtime.get("deepseek", {}) or {}
        use_deepseek = bool(pipeline_cfg.get("use_deepseek", True))
        api_key = str(deepseek_cfg.get("api_key", "")).strip()
        if not use_deepseek or not api_key:
            self._cache[cache_key] = base
            return base

        try:
            client = DeepSeekClient(
                base_url=str(deepseek_cfg.get("base_url", "")).strip() or None,
                model=str(deepseek_cfg.get("model", "")).strip() or None,
                api_key=api_key,
            )
            system_prompt = (
                "You are a concise engineering action helper for a desktop data pipeline.\n"
                "Return strict JSON object with keys:\n"
                "title, purpose, preconditions, inputs, risks, next_steps.\n"
                "Each list field must be an array of short strings."
            )
            user_prompt = json.dumps(
                {
                    "action_id": action_id,
                    "template": template,
                    "context": context_payload,
                    "requirements": {
                        "language": "en",
                        "style": "direct, actionable",
                        "max_items_per_list": 5,
                    },
                },
                ensure_ascii=False,
            )
            result = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1, max_tokens=900)
            if isinstance(result, dict):
                base["source"] = "deepseek"
                base["title"] = str(result.get("title") or base["title"])
                base["purpose"] = str(result.get("purpose") or base["purpose"])
                base["preconditions"] = [str(x) for x in result.get("preconditions", []) if str(x).strip()]
                base["inputs"] = [str(x) for x in result.get("inputs", []) if str(x).strip()]
                base["risks"] = [str(x) for x in result.get("risks", []) if str(x).strip()]
                base["next_steps"] = [str(x) for x in result.get("next_steps", []) if str(x).strip()]
        except Exception as exc:
            if self._log_handler:
                self._log_handler(f"action help fallback for {action_id}: {exc}")
            base["source"] = "local_fallback"

        self._cache[cache_key] = base
        return base
