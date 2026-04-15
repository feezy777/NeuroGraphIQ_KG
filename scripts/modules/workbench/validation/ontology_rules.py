from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _merge_review_note_json(existing: str, extra: Dict[str, Any]) -> str:
    base: Dict[str, Any] = {}
    if existing:
        try:
            base = json.loads(existing)
            if not isinstance(base, dict):
                base = {"_legacy_text": existing}
        except json.JSONDecodeError:
            base = {"_legacy_text": existing}
    merged = {**base, **extra}
    return json.dumps(merged, ensure_ascii=False)


def _issue(
    code: str,
    message: str,
    field: str = "",
    *,
    severity_override: Optional[str] = None,
    severity_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    sev = "warn"
    if severity_map and code in severity_map:
        sev = severity_map[code]
    elif severity_override:
        sev = severity_override
    return {"code": code, "severity": sev, "message": message, "field": field}


class OntologyRuleEngine:
    """Loads compiled ruleset JSON and evaluates region / circuit / connection candidates."""

    def __init__(self, root_dir: str, cfg: Dict[str, Any]) -> None:
        self._root = Path(root_dir).resolve()
        self._cfg = dict(cfg or {})
        self._data: Dict[str, Any] = {}
        self._path_resolved: Optional[Path] = None
        self._load_error: str = ""
        self.reload()

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled")) and bool(self._data) and not self._load_error

    @property
    def load_error(self) -> str:
        return self._load_error

    @property
    def rules_version(self) -> str:
        return str(self._data.get("version", ""))

    @property
    def raw(self) -> Dict[str, Any]:
        return dict(self._data)

    def reload(self) -> None:
        self._load_error = ""
        rel = (self._cfg.get("path") or "artifacts/ontology/ruleset.json").replace("\\", "/")
        path = (self._root / rel).resolve()
        self._path_resolved = path
        if not path.exists():
            self._data = {}
            self._load_error = f"ruleset_missing:{path}"
            return
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._data = {}
            self._load_error = f"ruleset_parse_error:{exc}"

    def _severity_map(self) -> Dict[str, str]:
        sm = self._cfg.get("issue_severity") or {}
        out = {
            "parent_not_allowed": "hard",
            "invalid_domain_range": "hard",
            "invalid_class": "warn",
            "unknown_term": "warn",
            "invalid_circuit_kind": "warn",
            "invalid_connection_modality": "warn",
            "granularity_mismatch": "warn",
        }
        out.update({k: v for k, v in sm.items() if isinstance(k, str) and isinstance(v, str)})
        return out

    def _require_known_terms(self) -> bool:
        return bool(self._cfg.get("require_known_terms"))

    def _resolve_synonym(self, name: str) -> str:
        sm = self._data.get("synonymMap") or {}
        k = _norm_key(name)
        if k in sm:
            return _norm_key(str(sm[k]))
        return k

    def _labels_index(self) -> Dict[str, str]:
        """Lower label -> canonical slug key for parentRules lookup."""
        idx: Dict[str, str] = {}
        for _iri, meta in (self._data.get("termMap") or {}).items():
            if not isinstance(meta, dict):
                continue
            can = _norm_key(str(meta.get("canonical", "")))
            if can:
                idx[can] = can
            for lab in meta.get("labels") or []:
                idx[_norm_key(str(lab))] = can or _norm_key(str(lab))
        return idx

    def _name_known(self, en: str, cn: str) -> bool:
        if not self._data.get("termMap"):
            return True
        idx = self._labels_index()
        for part in (en, cn):
            k = self._resolve_synonym(part)
            if k and k in idx:
                return True
        return False

    def evaluate_region(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        smap = self._severity_map()

        en = (candidate.get("en_name_candidate") or candidate.get("name") or "").strip()
        cn = (candidate.get("cn_name_candidate") or "").strip()
        parent = (candidate.get("parent_region_candidate") or "").strip()
        gran = (candidate.get("granularity_candidate") or "").strip().lower()
        cat = (candidate.get("region_category_candidate") or "brain_region").strip().lower()

        class_rules = (self._data.get("classRules") or {}).get("region") or {}
        allowed_cats = [str(x).lower() for x in (class_rules.get("allowed") or [])]
        if allowed_cats and cat not in allowed_cats:
            issues.append(
                _issue(
                    "invalid_class",
                    f"region_category '{cat}' not in allowed list",
                    "region_category_candidate",
                    severity_map=smap,
                )
            )

        if self._require_known_terms() and not self._name_known(en, cn):
            issues.append(
                _issue(
                    "unknown_term",
                    f"primary names not found in termMap/synonymMap: en={en!r} cn={cn!r}",
                    "en_name_candidate",
                    severity_map=smap,
                )
            )

        pr = self._data.get("parentRules") or {}
        child_key = self._resolve_synonym(en) or _norm_key(en)
        if not child_key and cn:
            child_key = self._resolve_synonym(cn) or _norm_key(cn)
        # parentRules keys may be canonical English names
        matched_key = None
        for k in pr.keys():
            if _norm_key(str(k)) == child_key or _norm_key(str(k)) == _norm_key(en):
                matched_key = str(k)
                break
        if matched_key and parent:
            allowed = [str(x).lower() for x in (pr[matched_key].get("allowedParents") or [])]
            pnorm = _norm_key(parent)
            if allowed and pnorm not in allowed:
                issues.append(
                    _issue(
                        "parent_not_allowed",
                        f"parent {parent!r} not allowed for {matched_key}; allowed={allowed}",
                        "parent_region_candidate",
                        severity_map=smap,
                    )
                )

        grules = (self._data.get("granularityRules") or {}).get("region") or {}
        if gran and gran in grules:
            # optional: parent granularity vs child — requires parent candidate; skip if empty
            pass

        hard = any(i.get("severity") == "hard" for i in issues)
        return {
            "issues": issues,
            "issues_count": len(issues),
            "has_hard": hard,
            "rules_version": self.rules_version,
        }

    def evaluate_circuit(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        smap = self._severity_map()
        kind = (candidate.get("circuit_kind_candidate") or "unknown").strip().lower()
        allowed = [str(x).lower() for x in ((self._data.get("classRules") or {}).get("circuit") or {}).get("allowedKinds") or []]
        if allowed and kind not in allowed:
            issues.append(
                _issue(
                    "invalid_circuit_kind",
                    f"circuit_kind {kind!r} not in allowedKinds",
                    "circuit_kind_candidate",
                    severity_map=smap,
                )
            )
        for n in candidate.get("nodes") or []:
            g = (n.get("granularity_candidate") or "").strip().lower()
            cg = (candidate.get("granularity_candidate") or "").strip().lower()
            if g and cg and g != cg:
                issues.append(
                    _issue(
                        "granularity_mismatch",
                        f"node granularity {g!r} != circuit {cg!r}",
                        "nodes",
                        severity_map=smap,
                    )
                )
        hard = any(i.get("severity") == "hard" for i in issues)
        return {"issues": issues, "issues_count": len(issues), "has_hard": hard, "rules_version": self.rules_version}

    def evaluate_connection(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        smap = self._severity_map()
        mod = (candidate.get("connection_modality_candidate") or "unknown").strip().lower()
        allowed = [str(x).lower() for x in ((self._data.get("classRules") or {}).get("connection") or {}).get("allowedModalities") or []]
        if allowed and mod not in allowed:
            issues.append(
                _issue(
                    "invalid_connection_modality",
                    f"modality {mod!r} not in allowedModalities",
                    "connection_modality_candidate",
                    severity_map=smap,
                )
            )

        g = (candidate.get("granularity_candidate") or "").strip().lower()
        rr = (self._data.get("relationRules") or {}).get("connection") or []
        for rule in rr:
            if not isinstance(rule, dict):
                continue
            dom = str(rule.get("sourceGranularity") or rule.get("domain") or "").strip().lower()
            rng = str(rule.get("targetGranularity") or rule.get("range") or "").strip().lower()
            if not dom or not rng or not g:
                continue
            sev = str(rule.get("severity", "warn"))
            if sev not in ("hard", "warn"):
                sev = "warn"
            # Single granularity on the candidate: when rule specifies domain==range, both ends must match that tier.
            if dom == rng and g != dom:
                issues.append(
                    {
                        "code": "invalid_domain_range",
                        "severity": sev,
                        "message": f"rule {rule.get('id', '')}: expected granularity {dom!r}, got {g!r}",
                        "field": "granularity_candidate",
                    }
                )
            elif dom != rng:
                # Without per-end granularity fields, only flag when candidate tier is outside {dom, rng}
                if g not in {dom, rng}:
                    issues.append(
                        {
                            "code": "invalid_domain_range",
                            "severity": sev,
                            "message": f"rule {rule.get('id', '')}: granularity {g!r} not in domain/range {dom!r}/{rng!r}",
                            "field": "granularity_candidate",
                        }
                    )

        hard = any(i.get("severity") == "hard" for i in issues)
        return {"issues": issues, "issues_count": len(issues), "has_hard": hard, "rules_version": self.rules_version}

    def should_fail_stage(self, eval_result: Dict[str, Any], policy: str) -> bool:
        if policy != "hard":
            return False
        return bool(eval_result.get("has_hard"))

    def ontology_check_payload(self, eval_result: Dict[str, Any], entity: str) -> Dict[str, Any]:
        return {
            "entity": entity,
            "rules_version": eval_result.get("rules_version", ""),
            "issues": eval_result.get("issues", []),
            "issues_count": eval_result.get("issues_count", 0),
        }


def merge_candidate_ontology_note(existing_note: str, ontology_check: Dict[str, Any]) -> str:
    return _merge_review_note_json(existing_note, {"ontology_check": ontology_check})


def engine_from_runtime(root_dir: str, runtime: Dict[str, Any]) -> OntologyRuleEngine:
    cfg = (runtime.get("pipeline") or {}).get("ontology_rules") or {}
    return OntologyRuleEngine(root_dir, cfg)


def refresh_engine(engine: OntologyRuleEngine, runtime: Dict[str, Any]) -> None:
    cfg = (runtime.get("pipeline") or {}).get("ontology_rules") or {}
    engine._cfg = dict(cfg)
    engine.reload()
