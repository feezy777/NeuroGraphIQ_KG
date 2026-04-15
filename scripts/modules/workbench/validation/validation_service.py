from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..common.id_utils import make_id
from ..common.models import ValidationRun
from .ontology_rules import OntologyRuleEngine


class ValidationService:
    def __init__(self, ontology_engine: Optional[OntologyRuleEngine] = None) -> None:
        self._ontology_engine = ontology_engine

    def set_ontology_engine(self, engine: Optional[OntologyRuleEngine]) -> None:
        self._ontology_engine = engine

    def run_validation(self, file_id: str, candidates: Dict[str, Any], mode: str = "local") -> ValidationRun:
        entity_count = len(candidates.get("candidate_entities", []))
        relation_count = len(candidates.get("candidate_relations", []))
        connection_count = len(candidates.get("candidate_connections", []))
        circuit_count = len(candidates.get("candidate_circuits", []))

        structure_check = {
            "status": "PASS" if entity_count else "WARN",
            "detail": f"entities={entity_count} relations={relation_count}",
        }

        ontology_rule_check = self._run_ontology_checks(candidates, mode)

        model_coarse_check = {
            "status": "PASS" if mode == "deepseek" else "WARN",
            "detail": f"model_coarse_check placeholder mode={mode}",
        }
        multi_model_review = {
            "status": "PENDING",
            "detail": "multi-model/human review placeholder",
        }

        oc_status = str(ontology_rule_check.get("status", "WARN"))
        base_score = 0.85 if mode == "deepseek" else 0.68
        issue_penalty = min(0.35, int(ontology_rule_check.get("issues_total", 0) or 0) * 0.03)
        score = max(0.25, base_score - issue_penalty)
        if oc_status == "FAIL":
            score = min(score, 0.45)
        if oc_status == "FAIL":
            overall = "WARN"
        elif score >= 0.8:
            overall = "PASS"
        else:
            overall = "WARN"

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

    def _iter_region_like(self, candidates: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for key in ("region_candidates", "candidate_regions"):
            for x in candidates.get(key) or []:
                if isinstance(x, dict):
                    out.append(x)
        for e in candidates.get("candidate_entities") or []:
            if isinstance(e, dict) and (
                "en_name_candidate" in e
                or "granularity_candidate" in e
                or str(e.get("entity_type", "")).lower() in {"region", "brain_region", "candidate_region"}
            ):
                out.append(e)
        return out

    def _run_ontology_checks(self, candidates: Dict[str, Any], mode: str) -> Dict[str, Any]:
        eng = self._ontology_engine
        if not eng or not eng.enabled:
            return {
                "status": "SKIPPED",
                "detail": eng.load_error if eng and eng.load_error else "ontology_rules_disabled",
                "mode": mode,
                "issues_total": 0,
                "by_entity": {},
            }

        all_issues: List[Dict[str, Any]] = []
        by_entity: Dict[str, Any] = {"region": [], "circuit": [], "connection": []}

        for row in self._iter_region_like(candidates):
            ev = eng.evaluate_region(row)
            for i in ev.get("issues", []):
                i2 = dict(i)
                i2["candidate_id"] = row.get("id", "")
                all_issues.append(i2)
            by_entity["region"].append({"candidate_id": row.get("id", ""), **ev})

        for row in candidates.get("candidate_circuits") or []:
            if not isinstance(row, dict):
                continue
            ev = eng.evaluate_circuit(row)
            for i in ev.get("issues", []):
                i2 = dict(i)
                i2["candidate_id"] = row.get("id", "")
                all_issues.append(i2)
            by_entity["circuit"].append({"candidate_id": row.get("id", ""), **ev})

        for row in candidates.get("candidate_connections") or []:
            if not isinstance(row, dict):
                continue
            ev = eng.evaluate_connection(row)
            for i in ev.get("issues", []):
                i2 = dict(i)
                i2["candidate_id"] = row.get("id", "")
                all_issues.append(i2)
            by_entity["connection"].append({"candidate_id": row.get("id", ""), **ev})

        hard = any(i.get("severity") == "hard" for i in all_issues)
        status = "PASS" if not all_issues else ("FAIL" if hard else "WARN")
        return {
            "status": status,
            "detail": f"rules_version={eng.rules_version} issues={len(all_issues)}",
            "mode": mode,
            "issues_total": len(all_issues),
            "has_hard": hard,
            "rules_version": eng.rules_version,
            "issues": all_issues[:200],
            "by_entity": by_entity,
        }
