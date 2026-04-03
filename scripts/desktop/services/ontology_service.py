from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import yaml

from scripts.desktop.models import GateDecision, OntologyBaseline, OntologyImportResult
from scripts.desktop.state_store import DesktopStateStore
from scripts.services.ontology_gate import load_ontology_baseline
from scripts.services.runtime_config import load_runtime_config, save_runtime_config
from scripts.utils.io_utils import write_json

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY_CONFIG_DIR = PROJECT_ROOT / "configs" / "ontology"
ALLOWED_EXTENSIONS = {".rdf", ".owl", ".xml"}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(payload, dict):
        return payload
    return {}


class OntologyService:
    def __init__(self, state_store: DesktopStateStore, persist_runtime_config: bool = True):
        self._state_store = state_store
        self._persist_runtime_config = persist_runtime_config
        self._baseline_dir = state_store.path.parent / "ontology_baselines"
        self._baseline_dir.mkdir(parents=True, exist_ok=True)

    def import_ontology(self, source_path: str | Path) -> OntologyImportResult:
        path = Path(source_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return OntologyImportResult(success=False, message=f"Ontology file not found: {path}")
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            return OntologyImportResult(
                success=False,
                message=f"Unsupported ontology format: {path.suffix}. Expected .rdf/.owl/.xml",
            )

        baseline_raw = load_ontology_baseline(ontology_path=path, ontology_config_dir=ONTOLOGY_CONFIG_DIR)
        parse_errors = [str(item) for item in baseline_raw.get("parse_errors", [])]
        if parse_errors:
            return OntologyImportResult(success=False, message="Ontology parse failed: " + " | ".join(parse_errors[:3]))

        digest = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
        loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        version_id = f"ont_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{digest}"
        baseline = OntologyBaseline(
            version_id=version_id,
            source_path=str(path),
            loaded_at=loaded_at,
            classes=[str(x) for x in baseline_raw.get("classes", [])],
            relations=[str(x) for x in baseline_raw.get("object_properties", [])],
            enums={str(k): [str(v) for v in vals] for k, vals in dict(baseline_raw.get("enum_values", {})).items()},
            mapping_snapshot={
                "class_mapping": _read_yaml(ONTOLOGY_CONFIG_DIR / "class_mapping.yaml"),
                "property_mapping": _read_yaml(ONTOLOGY_CONFIG_DIR / "property_mapping.yaml"),
                "constraint_mapping": _read_yaml(ONTOLOGY_CONFIG_DIR / "constraint_mapping.yaml"),
                "split_table_mapping": _read_yaml(ONTOLOGY_CONFIG_DIR / "split_table_mapping.yaml"),
            },
            parse_errors=parse_errors,
        )
        baseline_path = self._baseline_dir / f"{version_id}.json"
        write_json(baseline_path, baseline.to_dict())

        state = self._state_store.load()
        state["active_ontology"] = baseline.to_dict()
        self._state_store.save(state)

        if self._persist_runtime_config:
            runtime = load_runtime_config()
            runtime.setdefault("ontology", {})
            runtime["ontology"]["path"] = str(path)
            save_runtime_config(runtime)
        return OntologyImportResult(success=True, message=f"Ontology imported: {path.name}", baseline=baseline)

    def active_baseline(self) -> OntologyBaseline | None:
        state = self._state_store.load()
        payload = state.get("active_ontology")
        if not isinstance(payload, dict):
            return None
        return OntologyBaseline(
            version_id=str(payload.get("version_id") or ""),
            source_path=str(payload.get("source_path") or ""),
            loaded_at=str(payload.get("loaded_at") or ""),
            classes=[str(x) for x in payload.get("classes", [])],
            relations=[str(x) for x in payload.get("relations", [])],
            enums={str(k): [str(v) for v in vals] for k, vals in dict(payload.get("enums", {})).items()},
            mapping_snapshot=dict(payload.get("mapping_snapshot", {})),
            parse_errors=[str(x) for x in payload.get("parse_errors", [])],
        )

    def gate_decision(self) -> GateDecision:
        active = self.active_baseline()
        if not active:
            return GateDecision(
                allow_preprocess=False,
                allow_preview=False,
                allow_fine_process=False,
                allow_load=False,
                block_reason="ontology_not_imported",
            )
        if active.parse_errors:
            return GateDecision(
                allow_preprocess=False,
                allow_preview=False,
                allow_fine_process=False,
                allow_load=False,
                block_reason="ontology_parse_failed",
            )
        return GateDecision(
            allow_preprocess=True,
            allow_preview=True,
            allow_fine_process=True,
            allow_load=True,
            block_reason="",
        )
