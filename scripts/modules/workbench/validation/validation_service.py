from __future__ import annotations

from typing import Any, Dict

from ..common.id_utils import make_id
from ..common.models import ValidationRun


class ValidationService:
    def run_validation(self, file_id: str, candidates: Dict[str, Any], mode: str = "local") -> ValidationRun:
        entity_count = len(candidates.get("candidate_entities", []))
        relation_count = len(candidates.get("candidate_relations", []))
        connection_count = len(candidates.get("candidate_connections", []))
        circuit_count = len(candidates.get("candidate_circuits", []))

        structure_check = {
            "status": "PASS" if entity_count else "WARN",
            "detail": f"entities={entity_count} relations={relation_count}",
        }
        ontology_rule_check = {
            "status": "WARN",
            "detail": "ontology/rule validator placeholder for stage-1",
        }
        model_coarse_check = {
            "status": "PASS" if mode == "deepseek" else "WARN",
            "detail": f"model_coarse_check placeholder mode={mode}",
        }
        multi_model_review = {
            "status": "PENDING",
            "detail": "multi-model/human review placeholder",
        }
        score = 0.85 if mode == "deepseek" else 0.68
        overall = "PASS" if score >= 0.8 else "WARN"

        return ValidationRun(
            run_id=make_id("val"),
            file_id=file_id,
            structure_check=structure_check,
            ontology_rule_check=ontology_rule_check,
            model_coarse_check=model_coarse_check,
            multi_model_review=multi_model_review,
            overall_label=overall,
            overall_score=score,
        )
