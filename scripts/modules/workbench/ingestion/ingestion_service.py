from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from .circuit_identity import CircuitIdentityService
from .region_identity import RegionIdentityService
from ..extraction.brain_region_granularity import staging_gate_reason
from ..validation.ontology_rules import merge_candidate_ontology_note

LATERALITY_ALLOWED = {"left", "right", "midline", "bilateral"}
GRANULARITY_ALLOWED = {"major", "sub", "allen"}
CIRCUIT_KIND_ALLOWED = {"structural", "functional", "inferred", "unknown"}
LOOP_TYPE_ALLOWED = {"strict", "inferred", "functional"}
CONNECTION_MODALITY_ALLOWED = {"structural", "functional", "effective", "unknown"}
EVIDENCE_TYPE_ALLOWED = {"paper", "abstract", "database_record", "review", "manual_note"}
LOW_CONFIDENCE_THRESHOLD = 0.60


def _ontology_stage_eval(
    candidate: Dict[str, Any],
    entity: str,
    ontology_context: Optional[Dict[str, Any]],
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Returns (ok_to_proceed, fail_reason, ontology_check_payload_if_issues)."""
    if not ontology_context:
        return True, "", None
    eng = ontology_context.get("engine")
    if not eng or not getattr(eng, "enabled", False):
        return True, "", None
    pol = ontology_context.get("stage_policy", "warn")
    if entity == "region":
        ev = eng.evaluate_region(candidate)
    elif entity == "circuit":
        ev = eng.evaluate_circuit(candidate)
    else:
        ev = eng.evaluate_connection(candidate)
    oc = eng.ontology_check_payload(ev, entity)
    if eng.should_fail_stage(ev, pol):
        codes = [str(i.get("code", "")) for i in ev.get("issues", []) if i.get("severity") == "hard"]
        return False, f"ontology_rules_hard:{','.join(codes)}", oc
    if ev.get("issues"):
        return True, "", oc
    return True, "", None


def _make_id(prefix: str) -> str:
    stamp = str(int(time.time() * 1000))
    entropy = f"{time.time_ns()}_{uuid.uuid4().hex}"
    suffix = hashlib.sha1(entropy.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{stamp}_{suffix}"


class IngestionService:
    def __init__(self) -> None:
        self._unverified_schema_ready: Dict[str, bool] = {}
        self._identity = RegionIdentityService()
        self._circuit_identity = CircuitIdentityService()

    def stage_regions_to_unverified(
        self,
        file_payload: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        unverified_cfg: Dict[str, Any],
        ontology_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not candidates:
            return {"status": "failed", "summary": {"success_count": 0, "failed_count": 0, "total": 0}, "details": []}

        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        details: List[Dict[str, Any]] = []
        db_cfg = self._db_cfg(unverified_cfg)
        try:
            with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    for candidate in candidates:
                        cid = candidate.get("id", "")
                        current_status = (candidate.get("status") or "").strip().lower()
                        if current_status not in {"approved", "reviewed", "ready_for_unverified", "staged"}:
                            details.append(
                                {
                                    "candidate_id": cid,
                                    "status": "failed",
                                    "reason": f"invalid_candidate_status:{current_status or 'empty'}",
                                    "unverified_region_id": "",
                                }
                            )
                            continue

                        granularity = (candidate.get("granularity_candidate") or "").strip().lower()
                        if granularity not in GRANULARITY_ALLOWED:
                            details.append(
                                {
                                    "candidate_id": cid,
                                    "status": "failed",
                                    "reason": f"invalid_granularity:{granularity or 'empty'}",
                                    "unverified_region_id": "",
                                }
                            )
                            continue

                        gate = staging_gate_reason(str(candidate.get("review_note") or ""))
                        if gate:
                            details.append(
                                {
                                    "candidate_id": cid,
                                    "status": "failed",
                                    "reason": f"granularity_policy:{gate}",
                                    "unverified_region_id": "",
                                }
                            )
                            continue

                        ok_ont, reason_ont, oc_ont = _ontology_stage_eval(candidate, "region", ontology_context)
                        if not ok_ont:
                            details.append(
                                {
                                    "candidate_id": cid,
                                    "status": "failed",
                                    "reason": reason_ont,
                                    "unverified_region_id": "",
                                }
                            )
                            continue

                        review_note_val = candidate.get("review_note", "")
                        if oc_ont and oc_ont.get("issues"):
                            review_note_val = merge_candidate_ontology_note(review_note_val, oc_ont)

                        uvr_id = _make_id("uvr")
                        payload = {
                            "id": uvr_id,
                            "source_candidate_region_id": cid,
                            "source_file_id": candidate.get("file_id", file_payload.get("file_id", "")),
                            "source_parsed_document_id": candidate.get("parsed_document_id", ""),
                            "granularity": granularity,
                            "en_name": (candidate.get("en_name_candidate") or "").strip(),
                            "cn_name": (candidate.get("cn_name_candidate") or "").strip(),
                            "alias": ", ".join(candidate.get("alias_candidates", [])),
                            "description": (candidate.get("source_text") or "").strip(),
                            "laterality": (candidate.get("laterality_candidate") or "").strip().lower(),
                            "region_category": (candidate.get("region_category_candidate") or "brain_region").strip(),
                            "parent_region_ref": (candidate.get("parent_region_candidate") or "").strip(),
                            "ontology_source": (candidate.get("ontology_source_candidate") or "workbench").strip(),
                            "data_source": file_payload.get("filename", ""),
                            "confidence": float(candidate.get("confidence", 0.0) or 0.0),
                            "validation_status": "validation_pending",
                            "promotion_status": "not_ready",
                            "review_status": "reviewed",
                            "review_note": review_note_val,
                        }
                        cur.execute(
                            f"""
                            insert into {schema}.unverified_region (
                              id, source_candidate_region_id, source_file_id, source_parsed_document_id,
                              granularity, en_name, cn_name, alias, description, laterality,
                              region_category, parent_region_ref, ontology_source, data_source, confidence,
                              validation_status, promotion_status, review_status, review_note, created_at, updated_at
                            ) values (
                              %(id)s, %(source_candidate_region_id)s, %(source_file_id)s, %(source_parsed_document_id)s,
                              %(granularity)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s, %(laterality)s,
                              %(region_category)s, %(parent_region_ref)s, %(ontology_source)s, %(data_source)s, %(confidence)s,
                              %(validation_status)s, %(promotion_status)s, %(review_status)s, %(review_note)s, now(), now()
                            )
                            on conflict (source_candidate_region_id) do update set
                              source_file_id=excluded.source_file_id,
                              source_parsed_document_id=excluded.source_parsed_document_id,
                              granularity=excluded.granularity,
                              en_name=excluded.en_name,
                              cn_name=excluded.cn_name,
                              alias=excluded.alias,
                              description=excluded.description,
                              laterality=excluded.laterality,
                              region_category=excluded.region_category,
                              parent_region_ref=excluded.parent_region_ref,
                              ontology_source=excluded.ontology_source,
                              data_source=excluded.data_source,
                              confidence=excluded.confidence,
                              validation_status='validation_pending',
                              promotion_status='not_ready',
                              review_status='reviewed',
                              review_note=excluded.review_note,
                              updated_at=now()
                            returning id
                            """,
                            payload,
                        )
                        uvr_row = cur.fetchone()
                        details.append(
                            {
                                "candidate_id": cid,
                                "status": "success",
                                "reason": "",
                                "unverified_region_id": uvr_row["id"] if uvr_row else "",
                            }
                        )
                conn.commit()
        except Exception as exc:
            reason = str(exc)
            failed = [
                {
                    "candidate_id": c.get("id", ""),
                    "status": "failed",
                    "reason": reason,
                    "unverified_region_id": "",
                }
                for c in candidates
            ]
            return {
                "status": "failed",
                "summary": {"success_count": 0, "failed_count": len(failed), "total": len(candidates)},
                "details": failed,
            }

        success_count = sum(1 for d in details if d.get("status") == "success")
        failed_count = len(details) - success_count
        return {
            "status": "success" if failed_count == 0 else "partial",
            "summary": {"success_count": success_count, "failed_count": failed_count, "total": len(details)},
            "details": details,
        }

    def list_unverified_regions(self, unverified_cfg: Dict[str, Any], source_file_id: str = "") -> List[Dict[str, Any]]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                sql = f"""
                select
                  r.*,
                  v.id as latest_validation_id,
                  v.validation_type as latest_validation_type,
                  v.validator_name as latest_validation_validator,
                  v.status as latest_validation_result,
                  v.score as latest_validation_score,
                  v.message as latest_validation_message,
                  v.detail_json as latest_validation_detail_json,
                  v.created_at as latest_validation_at,
                  p.id as latest_promotion_id,
                  p.target_table as latest_target_table,
                  p.target_region_id as latest_target_region_id,
                  p.region_code as latest_region_code,
                  p.status as latest_promotion_result,
                  p.message as latest_promotion_message,
                  p.created_at as latest_promotion_at
                from {schema}.unverified_region r
                left join lateral (
                  select *
                  from {schema}.unverified_region_validation vv
                  where vv.unverified_region_id = r.id
                  order by vv.created_at desc
                  limit 1
                ) v on true
                left join lateral (
                  select *
                  from {schema}.promotion_record pp
                  where pp.unverified_region_id = r.id
                  order by pp.created_at desc
                  limit 1
                ) p on true
                """
                params: List[Any] = []
                if source_file_id:
                    sql += " where r.source_file_id=%s"
                    params.append(source_file_id)
                sql += " order by r.created_at desc"
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return [self._row_to_unverified(r) for r in rows]

    def fetch_unverified_regions_for_candidates(
        self,
        unverified_cfg: Dict[str, Any],
        candidate_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """按 candidate_region.id 查询未验证库对应行（用于验证中心按颗粒度晋升）。"""
        if not candidate_ids:
            return []
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        seen: set[str] = set()
        uniq: List[str] = []
        for c in candidate_ids:
            c = (c or "").strip()
            if c and c not in seen:
                seen.add(c)
                uniq.append(c)
        if not uniq:
            return []
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                ph = ",".join(["%s"] * len(uniq))
                cur.execute(
                    f"""
                    select id, source_candidate_region_id, granularity, validation_status, promotion_status
                    from {schema}.unverified_region
                    where source_candidate_region_id in ({ph})
                    """,
                    uniq,
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def stage_circuits_to_unverified(
        self,
        file_payload: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        unverified_cfg: Dict[str, Any],
        ontology_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not candidates:
            return {"status": "failed", "summary": {"success_count": 0, "failed_count": 0, "total": 0}, "details": []}
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        details: List[Dict[str, Any]] = []
        db_cfg = self._db_cfg(unverified_cfg)
        try:
            with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    for candidate in candidates:
                        cid = candidate.get("id", "")
                        current_status = (candidate.get("status") or "").strip().lower()
                        if current_status not in {"approved", "reviewed", "ready_for_unverified", "staged"}:
                            details.append(
                                {
                                    "candidate_circuit_id": cid,
                                    "status": "failed",
                                    "reason": f"invalid_candidate_status:{current_status or 'empty'}",
                                    "unverified_circuit_id": "",
                                }
                            )
                            continue
                        granularity = (candidate.get("granularity_candidate") or "").strip().lower()
                        if granularity not in GRANULARITY_ALLOWED:
                            details.append(
                                {
                                    "candidate_circuit_id": cid,
                                    "status": "failed",
                                    "reason": f"invalid_granularity:{granularity or 'empty'}",
                                    "unverified_circuit_id": "",
                                }
                            )
                            continue

                        ok_ont, reason_ont, oc_ont = _ontology_stage_eval(candidate, "circuit", ontology_context)
                        if not ok_ont:
                            details.append(
                                {
                                    "candidate_circuit_id": cid,
                                    "status": "failed",
                                    "reason": reason_ont,
                                    "unverified_circuit_id": "",
                                }
                            )
                            continue

                        review_note_val = candidate.get("review_note", "")
                        if oc_ont and oc_ont.get("issues"):
                            review_note_val = merge_candidate_ontology_note(review_note_val, oc_ont)

                        uvc_id = _make_id("uvc")
                        payload = {
                            "id": uvc_id,
                            "source_candidate_circuit_id": cid,
                            "source_file_id": candidate.get("file_id", file_payload.get("file_id", "")),
                            "source_parsed_document_id": candidate.get("parsed_document_id", ""),
                            "granularity": granularity,
                            "en_name": (candidate.get("en_name_candidate") or "").strip(),
                            "cn_name": (candidate.get("cn_name_candidate") or "").strip(),
                            "alias": ", ".join(candidate.get("alias_candidates", [])),
                            "description": (candidate.get("description_candidate") or candidate.get("source_text") or "").strip(),
                            "circuit_kind": (candidate.get("circuit_kind_candidate") or "unknown").strip().lower(),
                            "loop_type": (candidate.get("loop_type_candidate") or "inferred").strip().lower(),
                            "cycle_verified": bool(candidate.get("cycle_verified_candidate", False)),
                            "confidence_circuit": float(candidate.get("confidence_circuit", 0.0) or 0.0),
                            "validation_status": "validation_pending",
                            "promotion_status": "not_ready",
                            "review_status": "reviewed",
                            "review_note": review_note_val,
                            "data_source": file_payload.get("filename", ""),
                            "evidence_json": self._json(self._extract_evidence_payload(candidate, file_payload)),
                        }
                        cur.execute(
                            f"""
                            insert into {schema}.unverified_circuit (
                              id, source_candidate_circuit_id, source_file_id, source_parsed_document_id,
                              granularity, en_name, cn_name, alias, description, circuit_kind, loop_type,
                              cycle_verified, confidence_circuit, validation_status, promotion_status,
                              review_status, review_note, data_source, evidence_json, created_at, updated_at
                            ) values (
                              %(id)s, %(source_candidate_circuit_id)s, %(source_file_id)s, %(source_parsed_document_id)s,
                              %(granularity)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s, %(circuit_kind)s, %(loop_type)s,
                              %(cycle_verified)s, %(confidence_circuit)s, %(validation_status)s, %(promotion_status)s,
                              %(review_status)s, %(review_note)s, %(data_source)s, %(evidence_json)s::jsonb, now(), now()
                            )
                            on conflict (source_candidate_circuit_id) do update set
                              source_file_id=excluded.source_file_id,
                              source_parsed_document_id=excluded.source_parsed_document_id,
                              granularity=excluded.granularity,
                              en_name=excluded.en_name,
                              cn_name=excluded.cn_name,
                              alias=excluded.alias,
                              description=excluded.description,
                              circuit_kind=excluded.circuit_kind,
                              loop_type=excluded.loop_type,
                              cycle_verified=excluded.cycle_verified,
                              confidence_circuit=excluded.confidence_circuit,
                              validation_status='validation_pending',
                              promotion_status='not_ready',
                              review_status='reviewed',
                              review_note=excluded.review_note,
                              data_source=excluded.data_source,
                              evidence_json=excluded.evidence_json,
                              updated_at=now()
                            returning id
                            """,
                            payload,
                        )
                        uvc_row = cur.fetchone()
                        uvc_id = uvc_row["id"] if uvc_row else uvc_id
                        cur.execute(f"delete from {schema}.unverified_circuit_node where unverified_circuit_id=%s", (uvc_id,))
                        for n in (candidate.get("nodes") or []):
                            node_order_raw = n.get("node_order", 1)
                            try:
                                node_order = int(node_order_raw) if node_order_raw not in (None, "") else 1
                            except Exception:
                                node_order = 1
                            cur.execute(
                                f"""
                                insert into {schema}.unverified_circuit_node (
                                  id, unverified_circuit_id, region_id_ref, granularity, node_order, role_label, created_at
                                ) values (%s,%s,%s,%s,%s,%s,now())
                                """,
                                (
                                    n.get("id") or n.get("node_id") or _make_id("uvcn"),
                                    uvc_id,
                                    (n.get("region_id_candidate") or "").strip(),
                                    (n.get("granularity_candidate") or granularity).strip().lower(),
                                    node_order,
                                    (n.get("role_label") or "").strip(),
                                ),
                            )
                        details.append(
                            {
                                "candidate_circuit_id": cid,
                                "status": "success",
                                "reason": "",
                                "unverified_circuit_id": uvc_id,
                            }
                        )
                conn.commit()
        except Exception as exc:
            reason = str(exc)
            failed = [
                {
                    "candidate_circuit_id": c.get("id", ""),
                    "status": "failed",
                    "reason": reason,
                    "unverified_circuit_id": "",
                }
                for c in candidates
            ]
            return {
                "status": "failed",
                "summary": {"success_count": 0, "failed_count": len(failed), "total": len(candidates)},
                "details": failed,
            }
        success_count = sum(1 for d in details if d.get("status") == "success")
        failed_count = len(details) - success_count
        return {
            "status": "success" if failed_count == 0 else "partial",
            "summary": {"success_count": success_count, "failed_count": failed_count, "total": len(details)},
            "details": details,
        }

    def stage_connections_to_unverified(
        self,
        file_payload: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        unverified_cfg: Dict[str, Any],
        ontology_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not candidates:
            return {"status": "failed", "summary": {"success_count": 0, "failed_count": 0, "total": 0}, "details": []}
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        details: List[Dict[str, Any]] = []
        db_cfg = self._db_cfg(unverified_cfg)
        try:
            with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    for candidate in candidates:
                        cid = candidate.get("id", "")
                        current_status = (candidate.get("status") or "").strip().lower()
                        if current_status not in {"approved", "reviewed", "ready_for_unverified", "staged"}:
                            details.append(
                                {
                                    "candidate_connection_id": cid,
                                    "status": "failed",
                                    "reason": f"invalid_candidate_status:{current_status or 'empty'}",
                                    "unverified_connection_id": "",
                                }
                            )
                            continue
                        granularity = (candidate.get("granularity_candidate") or "").strip().lower()
                        if granularity not in GRANULARITY_ALLOWED:
                            details.append(
                                {
                                    "candidate_connection_id": cid,
                                    "status": "failed",
                                    "reason": f"invalid_granularity:{granularity or 'empty'}",
                                    "unverified_connection_id": "",
                                }
                            )
                            continue

                        ok_ont, reason_ont, oc_ont = _ontology_stage_eval(candidate, "connection", ontology_context)
                        if not ok_ont:
                            details.append(
                                {
                                    "candidate_connection_id": cid,
                                    "status": "failed",
                                    "reason": reason_ont,
                                    "unverified_connection_id": "",
                                }
                            )
                            continue

                        review_note_val = candidate.get("review_note", "")
                        if oc_ont and oc_ont.get("issues"):
                            review_note_val = merge_candidate_ontology_note(review_note_val, oc_ont)

                        uvcn_id = _make_id("uvcn")
                        payload = {
                            "id": uvcn_id,
                            "source_candidate_connection_id": cid,
                            "source_file_id": candidate.get("file_id", file_payload.get("file_id", "")),
                            "source_parsed_document_id": candidate.get("parsed_document_id", ""),
                            "granularity": granularity,
                            "en_name": (candidate.get("en_name_candidate") or "").strip(),
                            "cn_name": (candidate.get("cn_name_candidate") or "").strip(),
                            "alias": ", ".join(candidate.get("alias_candidates", [])),
                            "description": (candidate.get("description_candidate") or candidate.get("source_text") or "").strip(),
                            "connection_modality": (candidate.get("connection_modality_candidate") or "unknown").strip().lower(),
                            "source_region_ref": (candidate.get("source_region_ref_candidate") or "").strip(),
                            "target_region_ref": (candidate.get("target_region_ref_candidate") or "").strip(),
                            "confidence": float(candidate.get("confidence", 0.0) or 0.0),
                            "direction_label": (candidate.get("direction_label") or "unknown").strip().lower(),
                            "extraction_method": (candidate.get("extraction_method") or "local_rule").strip(),
                            "review_note": review_note_val,
                            "data_source": file_payload.get("filename", ""),
                            "evidence_json": self._json(self._extract_evidence_payload(candidate, file_payload)),
                            "validation_status": "validation_pending",
                            "promotion_status": "not_ready",
                            "review_status": "reviewed",
                        }
                        cur.execute(
                            f"""
                            insert into {schema}.unverified_connection (
                              id, source_candidate_connection_id, source_file_id, source_parsed_document_id,
                              granularity, en_name, cn_name, alias, description, connection_modality,
                              source_region_ref, target_region_ref, confidence, direction_label, extraction_method,
                              validation_status, promotion_status, review_status, review_note, data_source, evidence_json, created_at, updated_at
                            ) values (
                              %(id)s, %(source_candidate_connection_id)s, %(source_file_id)s, %(source_parsed_document_id)s,
                              %(granularity)s, %(en_name)s, %(cn_name)s, %(alias)s, %(description)s, %(connection_modality)s,
                              %(source_region_ref)s, %(target_region_ref)s, %(confidence)s, %(direction_label)s, %(extraction_method)s,
                              %(validation_status)s, %(promotion_status)s, %(review_status)s, %(review_note)s, %(data_source)s, %(evidence_json)s::jsonb, now(), now()
                            )
                            on conflict (source_candidate_connection_id) do update set
                              source_file_id=excluded.source_file_id,
                              source_parsed_document_id=excluded.source_parsed_document_id,
                              granularity=excluded.granularity,
                              en_name=excluded.en_name,
                              cn_name=excluded.cn_name,
                              alias=excluded.alias,
                              description=excluded.description,
                              connection_modality=excluded.connection_modality,
                              source_region_ref=excluded.source_region_ref,
                              target_region_ref=excluded.target_region_ref,
                              confidence=excluded.confidence,
                              direction_label=excluded.direction_label,
                              extraction_method=excluded.extraction_method,
                              validation_status='validation_pending',
                              promotion_status='not_ready',
                              review_status='reviewed',
                              review_note=excluded.review_note,
                              data_source=excluded.data_source,
                              evidence_json=excluded.evidence_json,
                              updated_at=now()
                            returning id
                            """,
                            payload,
                        )
                        uvcn_row = cur.fetchone()
                        details.append(
                            {
                                "candidate_connection_id": cid,
                                "status": "success",
                                "reason": "",
                                "unverified_connection_id": uvcn_row["id"] if uvcn_row else "",
                            }
                        )
                conn.commit()
        except Exception as exc:
            reason = str(exc)
            failed = [
                {
                    "candidate_connection_id": c.get("id", ""),
                    "status": "failed",
                    "reason": reason,
                    "unverified_connection_id": "",
                }
                for c in candidates
            ]
            return {
                "status": "failed",
                "summary": {"success_count": 0, "failed_count": len(failed), "total": len(candidates)},
                "details": failed,
            }
        success_count = sum(1 for d in details if d.get("status") == "success")
        failed_count = len(details) - success_count
        return {
            "status": "success" if failed_count == 0 else "partial",
            "summary": {"success_count": success_count, "failed_count": failed_count, "total": len(details)},
            "details": details,
        }

    def list_unverified_circuits(self, unverified_cfg: Dict[str, Any], source_file_id: str = "") -> List[Dict[str, Any]]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                sql = f"""
                select
                  c.*,
                  v.id as latest_validation_id,
                  v.validation_type as latest_validation_type,
                  v.validator_name as latest_validation_validator,
                  v.status as latest_validation_result,
                  v.score as latest_validation_score,
                  v.message as latest_validation_message,
                  v.detail_json as latest_validation_detail_json,
                  v.created_at as latest_validation_at,
                  p.id as latest_promotion_id,
                  p.target_table as latest_target_table,
                  p.target_circuit_id as latest_target_circuit_id,
                  p.circuit_code as latest_circuit_code,
                  p.status as latest_promotion_result,
                  p.message as latest_promotion_message,
                  p.created_at as latest_promotion_at
                from {schema}.unverified_circuit c
                left join lateral (
                  select *
                  from {schema}.unverified_circuit_validation vv
                  where vv.unverified_circuit_id = c.id
                  order by vv.created_at desc
                  limit 1
                ) v on true
                left join lateral (
                  select *
                  from {schema}.circuit_promotion_record pp
                  where pp.unverified_circuit_id = c.id
                  order by pp.created_at desc
                  limit 1
                ) p on true
                """
                params: List[Any] = []
                if source_file_id:
                    sql += " where c.source_file_id=%s"
                    params.append(source_file_id)
                sql += " order by c.created_at desc"
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                out: List[Dict[str, Any]] = []
                for row in rows:
                    cur.execute(
                        f"select * from {schema}.unverified_circuit_node where unverified_circuit_id=%s order by node_order, created_at",
                        (row.get("id", ""),),
                    )
                    nodes = cur.fetchall()
                    out.append(self._row_to_unverified_circuit(row, nodes))
        return out

    def list_unverified_connections(self, unverified_cfg: Dict[str, Any], source_file_id: str = "") -> List[Dict[str, Any]]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                sql = f"""
                select
                  c.*,
                  v.id as latest_validation_id,
                  v.validation_type as latest_validation_type,
                  v.validator_name as latest_validation_validator,
                  v.status as latest_validation_result,
                  v.score as latest_validation_score,
                  v.message as latest_validation_message,
                  v.detail_json as latest_validation_detail_json,
                  v.created_at as latest_validation_at,
                  p.id as latest_promotion_id,
                  p.target_table as latest_target_table,
                  p.target_connection_id as latest_target_connection_id,
                  p.connection_code as latest_connection_code,
                  p.status as latest_promotion_result,
                  p.message as latest_promotion_message,
                  p.created_at as latest_promotion_at
                from {schema}.unverified_connection c
                left join lateral (
                  select *
                  from {schema}.unverified_connection_validation vv
                  where vv.unverified_connection_id = c.id
                  order by vv.created_at desc
                  limit 1
                ) v on true
                left join lateral (
                  select *
                  from {schema}.connection_promotion_record pp
                  where pp.unverified_connection_id = c.id
                  order by pp.created_at desc
                  limit 1
                ) p on true
                """
                params: List[Any] = []
                if source_file_id:
                    sql += " where c.source_file_id=%s"
                    params.append(source_file_id)
                sql += " order by c.created_at desc"
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return [self._row_to_unverified_connection(r) for r in rows]

    def validate_unverified_connection(
        self,
        unverified_connection_id: str,
        unverified_cfg: Dict[str, Any],
        production_cfg: Dict[str, Any],
        validator_name: str = "rule_connection_validator",
        validation_type: str = "rule",
    ) -> Dict[str, Any]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"select * from {schema}.unverified_connection where id=%s", (unverified_connection_id,))
                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "unverified_connection_not_found"}
                cur.execute(
                    f"update {schema}.unverified_connection set validation_status='validating', promotion_status='not_ready', updated_at=now() where id=%s",
                    (unverified_connection_id,),
                )
                check = self._validate_unverified_connection(row, production_cfg)
                errors = check["errors"]
                warnings = check["warnings"]
                failed_fields = check["failed_fields"]
                rule_checks = check["rule_checks"]
                rule_summary = check.get("rule_summary", {})
                low_confidence = bool(check.get("low_confidence", False))
                passed = len(errors) == 0
                score = max(0.0, min(1.0, 1.0 - (0.2 * len(errors)) - (0.05 * len(warnings))))
                status = "validation_passed" if passed else "validation_failed"
                promotion_status = "promotion_pending" if passed else "not_ready"
                message = "passed" if passed and not warnings else ("passed_with_warnings" if passed else ";".join(errors))
                detail_json = {
                    "errors": errors,
                    "warnings": warnings,
                    "failed_fields": failed_fields,
                    "rule_checks": rule_checks,
                    "rule_summary": rule_summary,
                    "low_confidence": low_confidence,
                }
                validation_id = _make_id("uvconval")
                cur.execute(
                    f"""
                    insert into {schema}.unverified_connection_validation (
                      id, unverified_connection_id, validation_type, validator_name, status, score, message, detail_json, created_at
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
                    """,
                    (
                        validation_id,
                        unverified_connection_id,
                        validation_type,
                        validator_name,
                        status,
                        score,
                        message,
                        self._json(detail_json),
                    ),
                )
                cur.execute(
                    f"update {schema}.unverified_connection set validation_status=%s, promotion_status=%s, updated_at=now() where id=%s",
                    (status, promotion_status, unverified_connection_id),
                )
            conn.commit()
        return {
            "success": passed,
            "unverified_connection_id": unverified_connection_id,
            "validation_status": status,
            "promotion_status": promotion_status,
            "score": score,
            "message": message,
            "errors": errors,
            "warnings": warnings,
            "failed_fields": failed_fields,
            "rule_checks": rule_checks,
            "rule_summary": rule_summary,
            "low_confidence": low_confidence,
        }

    def promote_unverified_connection(
        self,
        unverified_connection_id: str,
        unverified_cfg: Dict[str, Any],
        production_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        unverified_db = self._db_cfg(unverified_cfg)
        with psycopg.connect(**unverified_db, row_factory=dict_row) as uconn:
            with uconn.cursor() as ucur:
                ucur.execute(f"select * from {schema}.unverified_connection where id=%s", (unverified_connection_id,))
                row = ucur.fetchone()
                if not row:
                    return {"success": False, "error": "unverified_connection_not_found"}
                if row.get("validation_status") != "validation_passed":
                    return {
                        "success": False,
                        "error": "validation_not_passed",
                        "detail": {"validation_status": row.get("validation_status"), "promotion_status": row.get("promotion_status")},
                    }
                precheck = self._validate_unverified_connection(row, production_cfg)
                if precheck["errors"]:
                    return {
                        "success": False,
                        "error": "promotion_precheck_failed",
                        "detail": {
                            "errors": precheck["errors"],
                            "warnings": precheck["warnings"],
                            "failed_fields": precheck["failed_fields"],
                            "rule_checks": precheck["rule_checks"],
                            "rule_summary": precheck.get("rule_summary", {}),
                        },
                    }
                ucur.execute(
                    f"update {schema}.unverified_connection set promotion_status='promoting', updated_at=now() where id=%s",
                    (unverified_connection_id,),
                )
                try:
                    with psycopg.connect(**self._db_cfg(production_cfg), row_factory=dict_row) as pconn:
                        with pconn.cursor() as pcur:
                            insert_res = self._commit_one_connection(
                                pcur,
                                production_cfg.get("schema", "neurokg"),
                                row,
                            )
                        pconn.commit()

                    promo_id = _make_id("conpromo")
                    evidence_summary = insert_res.get("evidence", {})
                    promo_message = (
                        f"evidence_attached={evidence_summary.get('attached_count', 0)} "
                        f"reused={evidence_summary.get('reused_count', 0)} "
                        f"created={evidence_summary.get('created_count', 0)}"
                    )
                    ucur.execute(
                        f"""
                        insert into {schema}.connection_promotion_record (
                          id, unverified_connection_id, target_table, target_connection_id, connection_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (
                            promo_id,
                            unverified_connection_id,
                            insert_res.get("table", ""),
                            insert_res.get("primary_key", ""),
                            insert_res.get("connection_code", ""),
                            "promoted",
                            promo_message,
                        ),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_connection set promotion_status='promoted', updated_at=now() where id=%s",
                        (unverified_connection_id,),
                    )
                    uconn.commit()
                    return {
                        "success": True,
                        "unverified_connection_id": unverified_connection_id,
                        "source_candidate_connection_id": row.get("source_candidate_connection_id", ""),
                        "promotion": insert_res,
                        "rule_summary": precheck.get("rule_summary", {}),
                    }
                except ValueError as exc:
                    reason = str(exc)
                    detail = self._promotion_connection_error_detail(reason)
                    promo_id = _make_id("conpromo")
                    ucur.execute(
                        f"""
                        insert into {schema}.connection_promotion_record (
                          id, unverified_connection_id, target_table, target_connection_id, connection_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (promo_id, unverified_connection_id, "", "", "", "failed", reason),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_connection set promotion_status='failed', updated_at=now() where id=%s",
                        (unverified_connection_id,),
                    )
                    uconn.commit()
                    return {
                        "success": False,
                        "error": "promote_connection_precheck_failed",
                        "detail": {**detail, "rule_summary": precheck.get("rule_summary", {})},
                    }
                except Exception as exc:
                    reason = str(exc)
                    promo_id = _make_id("conpromo")
                    ucur.execute(
                        f"""
                        insert into {schema}.connection_promotion_record (
                          id, unverified_connection_id, target_table, target_connection_id, connection_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (promo_id, unverified_connection_id, "", "", "", "failed", reason),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_connection set promotion_status='failed', updated_at=now() where id=%s",
                        (unverified_connection_id,),
                    )
                    uconn.commit()
                    return {
                        "success": False,
                        "error": "promote_connection_failed",
                        "detail": {"message": reason, "rule_summary": precheck.get("rule_summary", {})},
                    }

    def validate_unverified_circuit(
        self,
        unverified_circuit_id: str,
        unverified_cfg: Dict[str, Any],
        production_cfg: Dict[str, Any],
        validator_name: str = "rule_circuit_validator",
        validation_type: str = "rule",
    ) -> Dict[str, Any]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"select * from {schema}.unverified_circuit where id=%s", (unverified_circuit_id,))
                circuit = cur.fetchone()
                if not circuit:
                    return {"success": False, "error": "unverified_circuit_not_found"}
                cur.execute(
                    f"select * from {schema}.unverified_circuit_node where unverified_circuit_id=%s order by node_order, created_at",
                    (unverified_circuit_id,),
                )
                nodes = cur.fetchall()
                cur.execute(
                    f"update {schema}.unverified_circuit set validation_status='validating', promotion_status='not_ready', updated_at=now() where id=%s",
                    (unverified_circuit_id,),
                )

                check = self._validate_unverified_circuit(circuit, nodes, production_cfg)
                errors = check["errors"]
                warnings = check["warnings"]
                failed_fields = check["failed_fields"]
                rule_checks = check["rule_checks"]
                rule_summary = check.get("rule_summary", {})
                low_confidence = bool(check.get("low_confidence", False))
                passed = len(errors) == 0
                score = max(0.0, min(1.0, 1.0 - (0.2 * len(errors)) - (0.05 * len(warnings))))
                status = "validation_passed" if passed else "validation_failed"
                promotion_status = "promotion_pending" if passed else "not_ready"
                message = "passed" if passed and not warnings else ("passed_with_warnings" if passed else ";".join(errors))
                detail_json = {
                    "errors": errors,
                    "warnings": warnings,
                    "failed_fields": failed_fields,
                    "rule_checks": rule_checks,
                    "rule_summary": rule_summary,
                    "low_confidence": low_confidence,
                }
                validation_id = _make_id("uvcval")
                cur.execute(
                    f"""
                    insert into {schema}.unverified_circuit_validation (
                      id, unverified_circuit_id, validation_type, validator_name, status, score, message, detail_json, created_at
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
                    """,
                    (
                        validation_id,
                        unverified_circuit_id,
                        validation_type,
                        validator_name,
                        status,
                        score,
                        message,
                        self._json(detail_json),
                    ),
                )
                cur.execute(
                    f"update {schema}.unverified_circuit set validation_status=%s, promotion_status=%s, updated_at=now() where id=%s",
                    (status, promotion_status, unverified_circuit_id),
                )
            conn.commit()
        return {
            "success": passed,
            "unverified_circuit_id": unverified_circuit_id,
            "validation_status": status,
            "promotion_status": promotion_status,
            "score": score,
            "message": message,
            "errors": errors,
            "warnings": warnings,
            "failed_fields": failed_fields,
            "rule_checks": rule_checks,
            "rule_summary": rule_summary,
            "low_confidence": low_confidence,
        }

    def promote_unverified_circuit(
        self,
        unverified_circuit_id: str,
        unverified_cfg: Dict[str, Any],
        production_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        unverified_db = self._db_cfg(unverified_cfg)
        with psycopg.connect(**unverified_db, row_factory=dict_row) as uconn:
            with uconn.cursor() as ucur:
                ucur.execute(f"select * from {schema}.unverified_circuit where id=%s", (unverified_circuit_id,))
                circuit = ucur.fetchone()
                if not circuit:
                    return {"success": False, "error": "unverified_circuit_not_found"}
                if circuit.get("validation_status") != "validation_passed":
                    return {
                        "success": False,
                        "error": "validation_not_passed",
                        "detail": {"validation_status": circuit.get("validation_status"), "promotion_status": circuit.get("promotion_status")},
                    }
                ucur.execute(
                    f"select * from {schema}.unverified_circuit_node where unverified_circuit_id=%s order by node_order, created_at",
                    (unverified_circuit_id,),
                )
                nodes = ucur.fetchall()
                precheck = self._validate_unverified_circuit(circuit, nodes, production_cfg)
                if precheck["errors"]:
                    return {
                        "success": False,
                        "error": "promotion_precheck_failed",
                        "detail": {
                            "errors": precheck["errors"],
                            "warnings": precheck["warnings"],
                            "failed_fields": precheck["failed_fields"],
                            "rule_checks": precheck["rule_checks"],
                            "rule_summary": precheck.get("rule_summary", {}),
                        },
                    }
                ucur.execute(
                    f"update {schema}.unverified_circuit set promotion_status='promoting', updated_at=now() where id=%s",
                    (unverified_circuit_id,),
                )
                try:
                    with psycopg.connect(**self._db_cfg(production_cfg), row_factory=dict_row) as pconn:
                        with pconn.cursor() as pcur:
                            insert_res = self._commit_one_circuit(
                                pcur,
                                production_cfg.get("schema", "neurokg"),
                                circuit,
                                nodes,
                            )
                        pconn.commit()
                    promo_id = _make_id("cpromo")
                    evidence_summary = insert_res.get("evidence", {})
                    promo_message = (
                        f"evidence_attached={evidence_summary.get('attached_count', 0)} "
                        f"reused={evidence_summary.get('reused_count', 0)} "
                        f"created={evidence_summary.get('created_count', 0)}"
                    )
                    ucur.execute(
                        f"""
                        insert into {schema}.circuit_promotion_record (
                          id, unverified_circuit_id, target_table, target_circuit_id, circuit_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (
                            promo_id,
                            unverified_circuit_id,
                            insert_res.get("table", ""),
                            insert_res.get("primary_key", ""),
                            insert_res.get("circuit_code", ""),
                            "promoted",
                            promo_message,
                        ),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_circuit set promotion_status='promoted', updated_at=now() where id=%s",
                        (unverified_circuit_id,),
                    )
                    uconn.commit()
                    return {
                        "success": True,
                        "unverified_circuit_id": unverified_circuit_id,
                        "source_candidate_circuit_id": circuit.get("source_candidate_circuit_id", ""),
                        "promotion": insert_res,
                        "rule_summary": precheck.get("rule_summary", {}),
                    }
                except ValueError as exc:
                    reason = str(exc)
                    detail = self._promotion_circuit_error_detail(reason)
                    promo_id = _make_id("cpromo")
                    ucur.execute(
                        f"""
                        insert into {schema}.circuit_promotion_record (
                          id, unverified_circuit_id, target_table, target_circuit_id, circuit_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (promo_id, unverified_circuit_id, "", "", "", "failed", reason),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_circuit set promotion_status='failed', updated_at=now() where id=%s",
                        (unverified_circuit_id,),
                    )
                    uconn.commit()
                    return {
                        "success": False,
                        "error": "promote_circuit_precheck_failed",
                        "detail": {**detail, "rule_summary": precheck.get("rule_summary", {})},
                    }
                except Exception as exc:
                    reason = str(exc)
                    promo_id = _make_id("cpromo")
                    ucur.execute(
                        f"""
                        insert into {schema}.circuit_promotion_record (
                          id, unverified_circuit_id, target_table, target_circuit_id, circuit_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (promo_id, unverified_circuit_id, "", "", "", "failed", reason),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_circuit set promotion_status='failed', updated_at=now() where id=%s",
                        (unverified_circuit_id,),
                    )
                    uconn.commit()
                    return {
                        "success": False,
                        "error": "promote_circuit_failed",
                        "detail": {"message": reason, "rule_summary": precheck.get("rule_summary", {})},
                    }

    def validate_unverified_region(
        self,
        unverified_region_id: str,
        unverified_cfg: Dict[str, Any],
        production_cfg: Dict[str, Any] | None = None,
        validator_name: str = "rule_basic_validator",
        validation_type: str = "rule",
    ) -> Dict[str, Any]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        with psycopg.connect(**db_cfg, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"select * from {schema}.unverified_region where id=%s", (unverified_region_id,))
                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "unverified_region_not_found"}
                cur.execute(
                    f"update {schema}.unverified_region set validation_status='validating', promotion_status='not_ready', updated_at=now() where id=%s",
                    (unverified_region_id,),
                )

                check_result = self._validate_unverified_row(
                    row,
                    cur=cur,
                    schema=schema,
                    production_cfg=production_cfg or {},
                )
                errors = check_result["errors"]
                warnings = check_result["warnings"]
                failed_fields = check_result["failed_fields"]
                rule_checks = check_result["rule_checks"]
                rule_summary = check_result.get("rule_summary", {})
                low_confidence = bool(check_result.get("low_confidence", False))
                passed = len(errors) == 0
                score = max(0.0, min(1.0, 1.0 - (0.2 * len(errors)) - (0.05 * len(warnings))))
                status = "validation_passed" if passed else "validation_failed"
                promotion_status = "promotion_pending" if passed else "not_ready"
                if passed:
                    message = "passed" if not warnings else "passed_with_warnings"
                else:
                    message = ";".join(errors)
                detail_json = {
                    "errors": errors,
                    "warnings": warnings,
                    "failed_fields": failed_fields,
                    "rule_checks": rule_checks,
                    "rule_summary": rule_summary,
                    "low_confidence": low_confidence,
                    "granularity": row.get("granularity", ""),
                    "laterality": row.get("laterality", ""),
                }

                validation_id = _make_id("uvval")
                cur.execute(
                    f"""
                    insert into {schema}.unverified_region_validation (
                      id, unverified_region_id, validation_type, validator_name, status, score, message, detail_json, created_at
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
                    """,
                    (
                        validation_id,
                        unverified_region_id,
                        validation_type,
                        validator_name,
                        status,
                        score,
                        message,
                        self._json(detail_json),
                    ),
                )
                cur.execute(
                    f"update {schema}.unverified_region set validation_status=%s, promotion_status=%s, updated_at=now() where id=%s",
                    (status, promotion_status, unverified_region_id),
                )
            conn.commit()
        return {
            "success": passed,
            "unverified_region_id": unverified_region_id,
            "validation_status": status,
            "promotion_status": promotion_status,
            "score": score,
            "message": message,
            "errors": errors,
            "warnings": warnings,
            "failed_fields": failed_fields,
            "rule_checks": rule_checks,
            "rule_summary": rule_summary,
            "low_confidence": low_confidence,
        }

    def promote_unverified_region(
        self,
        unverified_region_id: str,
        unverified_cfg: Dict[str, Any],
        production_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._ensure_unverified_schema(unverified_cfg)
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        unverified_db = self._db_cfg(unverified_cfg)
        with psycopg.connect(**unverified_db, row_factory=dict_row) as uconn:
            with uconn.cursor() as ucur:
                ucur.execute(f"select * from {schema}.unverified_region where id=%s", (unverified_region_id,))
                row = ucur.fetchone()
                if not row:
                    return {"success": False, "error": "unverified_region_not_found"}
                if row.get("validation_status") != "validation_passed":
                    return {
                        "success": False,
                        "error": "validation_not_passed",
                        "detail": {"validation_status": row.get("validation_status"), "promotion_status": row.get("promotion_status")},
                    }
                precheck = self._validate_unverified_row(row, production_cfg=production_cfg)
                if precheck["errors"]:
                    return {
                        "success": False,
                        "error": "promotion_precheck_failed",
                        "detail": {
                            "errors": precheck["errors"],
                            "warnings": precheck["warnings"],
                            "failed_fields": precheck["failed_fields"],
                            "rule_checks": precheck["rule_checks"],
                            "rule_summary": precheck.get("rule_summary", {}),
                        },
                    }
                ucur.execute(
                    f"update {schema}.unverified_region set promotion_status='promoting', updated_at=now() where id=%s",
                    (unverified_region_id,),
                )

                candidate = self._candidate_from_unverified(row)
                file_payload = {
                    "file_id": row.get("source_file_id", ""),
                    "filename": row.get("data_source", ""),
                }
                try:
                    with psycopg.connect(**self._db_cfg(production_cfg), row_factory=dict_row) as pconn:
                        with pconn.cursor() as pcur:
                            duplicate_warnings = self._find_final_duplicate_warnings(
                                pcur,
                                production_cfg.get("schema", "neurokg"),
                                row,
                            )
                            insert_res = self._commit_one(
                                pcur,
                                production_cfg.get("schema", "neurokg"),
                                file_payload,
                                candidate,
                            )
                            insert_res["warnings"] = duplicate_warnings
                        pconn.commit()

                    promo_id = _make_id("promo")
                    ucur.execute(
                        f"""
                        insert into {schema}.promotion_record (
                          id, unverified_region_id, target_table, target_region_id, region_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (
                            promo_id,
                            unverified_region_id,
                            insert_res.get("table", ""),
                            insert_res.get("primary_key", ""),
                            insert_res.get("region_code", ""),
                            "promoted",
                            "",
                        ),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_region set promotion_status='promoted', updated_at=now() where id=%s",
                        (unverified_region_id,),
                    )
                    uconn.commit()
                    return {
                        "success": True,
                        "unverified_region_id": unverified_region_id,
                        "source_candidate_region_id": row.get("source_candidate_region_id", ""),
                        "promotion": insert_res,
                        "rule_summary": precheck.get("rule_summary", {}),
                    }
                except ValueError as exc:
                    reason = str(exc)
                    detail = self._promotion_error_detail(reason)
                    promo_id = _make_id("promo")
                    ucur.execute(
                        f"""
                        insert into {schema}.promotion_record (
                          id, unverified_region_id, target_table, target_region_id, region_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (promo_id, unverified_region_id, "", "", "", "failed", reason),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_region set promotion_status='failed', updated_at=now() where id=%s",
                        (unverified_region_id,),
                    )
                    uconn.commit()
                    return {
                        "success": False,
                        "error": "promote_precheck_failed",
                        "detail": {**detail, "rule_summary": precheck.get("rule_summary", {})},
                    }
                except Exception as exc:
                    reason = str(exc)
                    promo_id = _make_id("promo")
                    ucur.execute(
                        f"""
                        insert into {schema}.promotion_record (
                          id, unverified_region_id, target_table, target_region_id, region_code, status, message, created_at
                        ) values (%s,%s,%s,%s,%s,%s,%s,now())
                        """,
                        (promo_id, unverified_region_id, "", "", "", "failed", reason),
                    )
                    ucur.execute(
                        f"update {schema}.unverified_region set promotion_status='failed', updated_at=now() where id=%s",
                        (unverified_region_id,),
                    )
                    uconn.commit()
                    return {
                        "success": False,
                        "error": "promote_failed",
                        "detail": {
                            "message": reason,
                            "failed_fields": [],
                            "rule_checks": {},
                            "rule_summary": precheck.get("rule_summary", {}),
                        },
                    }

    def _validate_unverified_row(
        self,
        row: Dict[str, Any],
        cur: psycopg.Cursor | None = None,
        schema: str = "neurokg_unverified",
        production_cfg: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        failed_fields: List[str] = []
        rule_checks: Dict[str, Any] = {}
        granularity = (row.get("granularity") or "").strip().lower()
        laterality = (row.get("laterality") or "").strip().lower()
        if granularity not in GRANULARITY_ALLOWED:
            errors.append(f"invalid_granularity:{granularity or 'empty'}")
            failed_fields.append("granularity")
            rule_checks["granularity"] = {"ok": False, "value": granularity or "", "allowed": sorted(GRANULARITY_ALLOWED)}
        else:
            rule_checks["granularity"] = {"ok": True, "value": granularity}

        if laterality not in LATERALITY_ALLOWED:
            errors.append(f"invalid_laterality:{laterality or 'empty'}")
            failed_fields.append("laterality")
            rule_checks["laterality"] = {"ok": False, "value": laterality or "", "allowed": sorted(LATERALITY_ALLOWED)}
        else:
            rule_checks["laterality"] = {"ok": True, "value": laterality}

        if not (row.get("region_category") or "").strip():
            errors.append("missing_region_category")
            failed_fields.append("region_category")
            rule_checks["region_category"] = {"ok": False}
        else:
            rule_checks["region_category"] = {"ok": True}

        if not (row.get("en_name") or row.get("cn_name")):
            errors.append("missing_region_name")
            failed_fields.append("en_name_or_cn_name")
            rule_checks["region_name"] = {"ok": False}
        else:
            rule_checks["region_name"] = {"ok": True}
        parent = (row.get("parent_region_ref") or "").strip()
        if granularity == "major" and parent:
            errors.append("major_region_parent_must_be_empty")
            failed_fields.append("parent_region_ref")
            rule_checks["parent"] = {"ok": False, "reason": "major_has_parent", "value": parent}
        if granularity == "sub" and not parent:
            errors.append("missing_parent_major_region_id")
            failed_fields.append("parent_major_region_id")
            rule_checks["parent"] = {"ok": False, "reason": "sub_missing_parent", "value": parent}
        if granularity == "sub" and parent and not parent.startswith("REG_MAJ_"):
            errors.append("invalid_parent_for_sub")
            failed_fields.append("parent_major_region_id")
            rule_checks["parent"] = {"ok": False, "reason": "sub_parent_prefix", "value": parent}
        if granularity == "allen" and not parent:
            errors.append("missing_parent_sub_region_id")
            failed_fields.append("parent_sub_region_id")
            rule_checks["parent"] = {"ok": False, "reason": "allen_missing_parent", "value": parent}
        if granularity == "allen" and parent and not parent.startswith("REG_SUB_"):
            errors.append("invalid_parent_for_allen")
            failed_fields.append("parent_sub_region_id")
            rule_checks["parent"] = {"ok": False, "reason": "allen_parent_prefix", "value": parent}
        if granularity == "major" and not parent:
            rule_checks["parent"] = {"ok": True, "reason": "major_no_parent"}
        elif granularity == "sub" and parent.startswith("REG_MAJ_"):
            rule_checks["parent"] = {"ok": True, "reason": "sub_parent_major", "value": parent}
        elif granularity == "allen" and parent.startswith("REG_SUB_"):
            rule_checks["parent"] = {"ok": True, "reason": "allen_parent_sub", "value": parent}

        if cur is not None:
            warnings.extend(self._find_unverified_duplicate_warnings(cur, schema, row))
        if production_cfg:
            try:
                prod_db = self._db_cfg(production_cfg)
                prod_schema = production_cfg.get("schema", "neurokg")
                with psycopg.connect(**prod_db, row_factory=dict_row) as pconn:
                    with pconn.cursor() as pcur:
                        warnings.extend(self._find_final_duplicate_warnings(pcur, prod_schema, row))
            except Exception as exc:
                warnings.append(f"final_duplicate_check_failed:{exc}")

        confidence_raw = row.get("confidence")
        try:
            confidence = float(confidence_raw if confidence_raw is not None else 0.0)
        except Exception:
            confidence = -1.0
        low_confidence = self._is_low_confidence(confidence)
        if low_confidence:
            warnings.append(f"low_confidence:{confidence_raw}")
        rule_checks["confidence"] = {"ok": confidence >= 0, "value": confidence_raw, "low_confidence": low_confidence}

        if warnings:
            rule_checks["duplicates"] = {"ok": True, "warnings": warnings}
        rule_summary = self._build_rule_summary(errors, warnings, rule_checks, failed_fields)
        return {
            "errors": errors,
            "warnings": warnings,
            "failed_fields": list(dict.fromkeys(failed_fields)),
            "rule_checks": rule_checks,
            "rule_summary": rule_summary,
            "low_confidence": low_confidence,
        }

    def _find_unverified_duplicate_warnings(self, cur: psycopg.Cursor, schema: str, row: Dict[str, Any]) -> List[str]:
        warnings: List[str] = []
        rid = row.get("id", "")
        granularity = (row.get("granularity") or "").strip().lower()
        en_name = (row.get("en_name") or "").strip().lower()
        cn_name = (row.get("cn_name") or "").strip().lower()
        aliases = self._normalize_aliases_from_csv(row.get("alias", ""))
        cur.execute(
            f"""
            select id, en_name, cn_name, alias
            from {schema}.unverified_region
            where id<>%s and granularity=%s and review_status<>'rejected'
            order by created_at desc
            limit 50
            """,
            (rid, granularity),
        )
        for other in cur.fetchall():
            oid = other.get("id", "")
            if en_name and (other.get("en_name") or "").strip().lower() == en_name:
                warnings.append(f"duplicate_en_name_in_unverified:{oid}")
            if cn_name and (other.get("cn_name") or "").strip().lower() == cn_name:
                warnings.append(f"duplicate_cn_name_in_unverified:{oid}")
            other_aliases = self._normalize_aliases_from_csv(other.get("alias", ""))
            common = sorted(aliases.intersection(other_aliases))
            if common:
                warnings.append(f"duplicate_alias_in_unverified:{oid}:{','.join(common)}")
        return warnings

    def _find_final_duplicate_warnings(
        self,
        cur: psycopg.Cursor,
        schema: str,
        unverified_row: Dict[str, Any],
    ) -> List[str]:
        warnings: List[str] = []
        granularity = (unverified_row.get("granularity") or "").strip().lower()
        if granularity not in GRANULARITY_ALLOWED:
            return warnings
        table, _, _ = self._table_route(granularity)
        en_name = (unverified_row.get("en_name") or "").strip().lower()
        cn_name = (unverified_row.get("cn_name") or "").strip().lower()
        aliases = list(self._normalize_aliases_from_csv(unverified_row.get("alias", "")))
        if en_name:
            cur.execute(
                f"select 1 from {schema}.{table} where lower(en_name)=%s limit 1",
                (en_name,),
            )
            if cur.fetchone():
                warnings.append("duplicate_en_name_in_final")
        if cn_name:
            cur.execute(
                f"select 1 from {schema}.{table} where lower(cn_name)=%s limit 1",
                (cn_name,),
            )
            if cur.fetchone():
                warnings.append("duplicate_cn_name_in_final")
        if aliases:
            cur.execute(
                f"select 1 from {schema}.{table} where alias && %s::text[] limit 1",
                (aliases,),
            )
            if cur.fetchone():
                warnings.append("duplicate_alias_in_final")
        return warnings

    @staticmethod
    def _normalize_aliases_from_csv(value: str) -> set[str]:
        return {x.strip().lower() for x in (value or "").split(",") if x.strip()}

    @staticmethod
    def _promotion_error_detail(reason: str) -> Dict[str, Any]:
        failed_map = {
            "invalid_granularity": ["granularity"],
            "invalid_laterality": ["laterality"],
            "missing_parent_for_sub": ["parent_major_region_id"],
            "missing_parent_for_allen": ["parent_sub_region_id"],
            "major_region_parent_must_be_empty": ["parent_region_ref"],
            "parent_major_region_not_found": ["parent_major_region_id"],
            "parent_sub_region_not_found": ["parent_sub_region_id"],
            "target_table_missing_columns": ["target_table_columns"],
            "invalid_parent_for_sub": ["parent_major_region_id"],
            "invalid_parent_for_allen": ["parent_sub_region_id"],
        }
        code = reason.split(":", 1)[0]
        return {
            "code": code,
            "message": reason,
            "failed_fields": failed_map.get(code, []),
            "rule_checks": {},
        }

    @staticmethod
    def _candidate_from_unverified(row: Dict[str, Any]) -> Dict[str, Any]:
        aliases = [x.strip() for x in (row.get("alias") or "").split(",") if x.strip()]
        return {
            "id": row.get("source_candidate_region_id", ""),
            "file_id": row.get("source_file_id", ""),
            "source_text": row.get("description", ""),
            "en_name_candidate": row.get("en_name", ""),
            "cn_name_candidate": row.get("cn_name", ""),
            "alias_candidates": aliases,
            "laterality_candidate": row.get("laterality", ""),
            "region_category_candidate": row.get("region_category", "brain_region"),
            "granularity_candidate": row.get("granularity", ""),
            "parent_region_candidate": row.get("parent_region_ref", ""),
            "ontology_source_candidate": row.get("ontology_source", "workbench"),
            "confidence": float(row.get("confidence") or 0.0),
            "low_confidence": self._is_low_confidence(float(row.get("confidence") or 0.0)),
            "extraction_method": "unverified_promote",
        }

    def _ensure_unverified_schema(self, unverified_cfg: Dict[str, Any]) -> None:
        cache_key = f"{unverified_cfg.get('host')}:{unverified_cfg.get('port')}:{unverified_cfg.get('dbname')}:{unverified_cfg.get('schema')}"
        if self._unverified_schema_ready.get(cache_key):
            return
        schema = unverified_cfg.get("schema", "neurokg_unverified")
        db_cfg = self._db_cfg(unverified_cfg)
        stmts = [
            f"create schema if not exists {schema}",
            f"""
            create table if not exists {schema}.unverified_region (
              id text primary key,
              source_candidate_region_id text not null unique,
              source_file_id text not null,
              source_parsed_document_id text not null default '',
              granularity text not null,
              en_name text not null default '',
              cn_name text not null default '',
              alias text not null default '',
              description text not null default '',
              laterality text not null default '',
              region_category text not null default 'brain_region',
              parent_region_ref text not null default '',
              ontology_source text not null default 'workbench',
              data_source text not null default '',
              confidence numeric(7,4) not null default 0,
              validation_status text not null default 'validation_pending',
              promotion_status text not null default 'not_ready',
              review_status text not null default 'reviewed',
              review_note text not null default '',
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.unverified_region_validation (
              id text primary key,
              unverified_region_id text not null,
              validation_type text not null default 'rule',
              validator_name text not null default '',
              status text not null,
              score numeric(7,4) not null default 0,
              message text not null default '',
              detail_json jsonb not null default '{{}}'::jsonb,
              created_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.promotion_record (
              id text primary key,
              unverified_region_id text not null,
              target_table text not null default '',
              target_region_id text not null default '',
              region_code text not null default '',
              status text not null,
              message text not null default '',
              created_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.unverified_circuit (
              id text primary key,
              source_candidate_circuit_id text not null unique,
              source_file_id text not null,
              source_parsed_document_id text not null default '',
              granularity text not null,
              en_name text not null default '',
              cn_name text not null default '',
              alias text not null default '',
              description text not null default '',
              circuit_kind text not null default 'unknown',
              loop_type text not null default 'inferred',
              cycle_verified boolean not null default false,
              confidence_circuit numeric(7,4) not null default 0,
              validation_status text not null default 'validation_pending',
              promotion_status text not null default 'not_ready',
              review_status text not null default 'reviewed',
              review_note text not null default '',
              data_source text not null default '',
              evidence_json jsonb not null default '[]'::jsonb,
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.unverified_circuit_node (
              id text primary key,
              unverified_circuit_id text not null,
              region_id_ref text not null default '',
              granularity text not null default 'unknown',
              node_order integer not null default 1,
              role_label text not null default '',
              created_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.unverified_circuit_validation (
              id text primary key,
              unverified_circuit_id text not null,
              validation_type text not null default 'rule',
              validator_name text not null default '',
              status text not null,
              score numeric(7,4) not null default 0,
              message text not null default '',
              detail_json jsonb not null default '{{}}'::jsonb,
              created_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.circuit_promotion_record (
              id text primary key,
              unverified_circuit_id text not null,
              target_table text not null default '',
              target_circuit_id text not null default '',
              circuit_code text not null default '',
              status text not null,
              message text not null default '',
              created_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.unverified_connection (
              id text primary key,
              source_candidate_connection_id text not null unique,
              source_file_id text not null,
              source_parsed_document_id text not null default '',
              granularity text not null,
              en_name text not null default '',
              cn_name text not null default '',
              alias text not null default '',
              description text not null default '',
              connection_modality text not null default 'unknown',
              source_region_ref text not null default '',
              target_region_ref text not null default '',
              confidence numeric(7,4) not null default 0,
              direction_label text not null default 'unknown',
              extraction_method text not null default 'local_rule',
              validation_status text not null default 'validation_pending',
              promotion_status text not null default 'not_ready',
              review_status text not null default 'reviewed',
              review_note text not null default '',
              data_source text not null default '',
              evidence_json jsonb not null default '[]'::jsonb,
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            )
            """,
            f"alter table {schema}.unverified_circuit add column if not exists evidence_json jsonb not null default '[]'::jsonb",
            f"alter table {schema}.unverified_connection add column if not exists evidence_json jsonb not null default '[]'::jsonb",
            f"""
            create table if not exists {schema}.unverified_connection_validation (
              id text primary key,
              unverified_connection_id text not null,
              validation_type text not null default 'rule',
              validator_name text not null default '',
              status text not null,
              score numeric(7,4) not null default 0,
              message text not null default '',
              detail_json jsonb not null default '{{}}'::jsonb,
              created_at timestamptz not null default now()
            )
            """,
            f"""
            create table if not exists {schema}.connection_promotion_record (
              id text primary key,
              unverified_connection_id text not null,
              target_table text not null default '',
              target_connection_id text not null default '',
              connection_code text not null default '',
              status text not null,
              message text not null default '',
              created_at timestamptz not null default now()
            )
            """,
            f"create index if not exists idx_uv_region_file on {schema}.unverified_region(source_file_id, created_at desc)",
            f"create index if not exists idx_uv_region_status on {schema}.unverified_region(validation_status, promotion_status)",
            f"create index if not exists idx_uv_validation_region on {schema}.unverified_region_validation(unverified_region_id, created_at desc)",
            f"create index if not exists idx_uv_promotion_region on {schema}.promotion_record(unverified_region_id, created_at desc)",
            f"create index if not exists idx_uv_circuit_file on {schema}.unverified_circuit(source_file_id, created_at desc)",
            f"create index if not exists idx_uv_circuit_status on {schema}.unverified_circuit(validation_status, promotion_status)",
            f"create index if not exists idx_uv_circuit_node_ref on {schema}.unverified_circuit_node(unverified_circuit_id, node_order)",
            f"create index if not exists idx_uv_circuit_validation_ref on {schema}.unverified_circuit_validation(unverified_circuit_id, created_at desc)",
            f"create index if not exists idx_uv_circuit_promotion_ref on {schema}.circuit_promotion_record(unverified_circuit_id, created_at desc)",
            f"create index if not exists idx_uv_connection_file on {schema}.unverified_connection(source_file_id, created_at desc)",
            f"create index if not exists idx_uv_connection_status on {schema}.unverified_connection(validation_status, promotion_status)",
            f"create index if not exists idx_uv_connection_validation_ref on {schema}.unverified_connection_validation(unverified_connection_id, created_at desc)",
            f"create index if not exists idx_uv_connection_promotion_ref on {schema}.connection_promotion_record(unverified_connection_id, created_at desc)",
        ]
        with psycopg.connect(**db_cfg) as conn:
            with conn.cursor() as cur:
                for stmt in stmts:
                    cur.execute(stmt)
            conn.commit()
        self._unverified_schema_ready[cache_key] = True

    @staticmethod
    def _row_to_unverified(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id", ""),
            "source_candidate_region_id": row.get("source_candidate_region_id", ""),
            "source_file_id": row.get("source_file_id", ""),
            "source_parsed_document_id": row.get("source_parsed_document_id", ""),
            "granularity": row.get("granularity", ""),
            "en_name": row.get("en_name", ""),
            "cn_name": row.get("cn_name", ""),
            "alias": row.get("alias", ""),
            "description": row.get("description", ""),
            "laterality": row.get("laterality", ""),
            "region_category": row.get("region_category", ""),
            "parent_region_ref": row.get("parent_region_ref", ""),
            "ontology_source": row.get("ontology_source", ""),
            "data_source": row.get("data_source", ""),
            "confidence": float(row.get("confidence") or 0.0),
            "low_confidence": self._is_low_confidence(float(row.get("confidence") or 0.0)),
            "validation_status": row.get("validation_status", "validation_pending"),
            "promotion_status": row.get("promotion_status", "not_ready"),
            "review_status": row.get("review_status", "reviewed"),
            "review_note": row.get("review_note", ""),
            "latest_validation_id": row.get("latest_validation_id", ""),
            "latest_validation_type": row.get("latest_validation_type", ""),
            "latest_validation_validator": row.get("latest_validation_validator", ""),
            "latest_validation_result": row.get("latest_validation_result", ""),
            "latest_validation_score": float(row.get("latest_validation_score") or 0.0),
            "latest_validation_message": row.get("latest_validation_message", ""),
            "latest_validation_detail_json": row.get("latest_validation_detail_json") or {},
            "rule_summary": (row.get("latest_validation_detail_json") or {}).get("rule_summary", {}),
            "rule_summary": (row.get("latest_validation_detail_json") or {}).get("rule_summary", {}),
            "latest_validation_at": str(row.get("latest_validation_at")).replace("+00:00", "Z")
            if row.get("latest_validation_at")
            else "",
            "latest_promotion_id": row.get("latest_promotion_id", ""),
            "target_table": row.get("latest_target_table", ""),
            "target_region_id": row.get("latest_target_region_id", ""),
            "region_code": row.get("latest_region_code", ""),
            "latest_promotion_result": row.get("latest_promotion_result", ""),
            "latest_promotion_message": row.get("latest_promotion_message", ""),
            "latest_promotion_at": str(row.get("latest_promotion_at")).replace("+00:00", "Z")
            if row.get("latest_promotion_at")
            else "",
            "created_at": str(row.get("created_at")).replace("+00:00", "Z") if row.get("created_at") else "",
            "updated_at": str(row.get("updated_at")).replace("+00:00", "Z") if row.get("updated_at") else "",
        }

    def _row_to_unverified_circuit(self, row: Dict[str, Any], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "id": row.get("id", ""),
            "source_candidate_circuit_id": row.get("source_candidate_circuit_id", ""),
            "source_file_id": row.get("source_file_id", ""),
            "source_parsed_document_id": row.get("source_parsed_document_id", ""),
            "granularity": row.get("granularity", ""),
            "en_name": row.get("en_name", ""),
            "cn_name": row.get("cn_name", ""),
            "alias": row.get("alias", ""),
            "description": row.get("description", ""),
            "circuit_kind": row.get("circuit_kind", "unknown"),
            "loop_type": row.get("loop_type", "inferred"),
            "cycle_verified": bool(row.get("cycle_verified", False)),
            "confidence_circuit": float(row.get("confidence_circuit") or 0.0),
            "low_confidence": self._is_low_confidence(float(row.get("confidence_circuit") or 0.0)),
            "validation_status": row.get("validation_status", "validation_pending"),
            "promotion_status": row.get("promotion_status", "not_ready"),
            "review_status": row.get("review_status", "reviewed"),
            "review_note": row.get("review_note", ""),
            "evidence_json": row.get("evidence_json") or [],
            "evidence_count": len(row.get("evidence_json") or []),
            "nodes": [
                {
                    "id": n.get("id", ""),
                    "region_id_ref": n.get("region_id_ref", ""),
                    "granularity": n.get("granularity", "unknown"),
                    "node_order": int(n.get("node_order")) if n.get("node_order") is not None else 1,
                    "role_label": n.get("role_label", ""),
                }
                for n in nodes
            ],
            "latest_validation_id": row.get("latest_validation_id", ""),
            "latest_validation_type": row.get("latest_validation_type", ""),
            "latest_validation_validator": row.get("latest_validation_validator", ""),
            "latest_validation_result": row.get("latest_validation_result", ""),
            "latest_validation_score": float(row.get("latest_validation_score") or 0.0),
            "latest_validation_message": row.get("latest_validation_message", ""),
            "latest_validation_detail_json": row.get("latest_validation_detail_json") or {},
            "rule_summary": (row.get("latest_validation_detail_json") or {}).get("rule_summary", {}),
            "latest_validation_at": str(row.get("latest_validation_at")).replace("+00:00", "Z")
            if row.get("latest_validation_at")
            else "",
            "latest_promotion_id": row.get("latest_promotion_id", ""),
            "target_table": row.get("latest_target_table", ""),
            "target_circuit_id": row.get("latest_target_circuit_id", ""),
            "circuit_code": row.get("latest_circuit_code", ""),
            "latest_promotion_result": row.get("latest_promotion_result", ""),
            "latest_promotion_message": row.get("latest_promotion_message", ""),
            "latest_promotion_at": str(row.get("latest_promotion_at")).replace("+00:00", "Z")
            if row.get("latest_promotion_at")
            else "",
            "created_at": str(row.get("created_at")).replace("+00:00", "Z") if row.get("created_at") else "",
            "updated_at": str(row.get("updated_at")).replace("+00:00", "Z") if row.get("updated_at") else "",
        }

    @staticmethod
    def _row_to_unverified_connection(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id", ""),
            "source_candidate_connection_id": row.get("source_candidate_connection_id", ""),
            "source_file_id": row.get("source_file_id", ""),
            "source_parsed_document_id": row.get("source_parsed_document_id", ""),
            "granularity": row.get("granularity", ""),
            "en_name": row.get("en_name", ""),
            "cn_name": row.get("cn_name", ""),
            "alias": row.get("alias", ""),
            "description": row.get("description", ""),
            "connection_modality": row.get("connection_modality", "unknown"),
            "source_region_ref": row.get("source_region_ref", ""),
            "target_region_ref": row.get("target_region_ref", ""),
            "confidence": float(row.get("confidence") or 0.0),
            "direction_label": row.get("direction_label", "unknown"),
            "extraction_method": row.get("extraction_method", "local_rule"),
            "validation_status": row.get("validation_status", "validation_pending"),
            "promotion_status": row.get("promotion_status", "not_ready"),
            "review_status": row.get("review_status", "reviewed"),
            "review_note": row.get("review_note", ""),
            "evidence_json": row.get("evidence_json") or [],
            "evidence_count": len(row.get("evidence_json") or []),
            "latest_validation_id": row.get("latest_validation_id", ""),
            "latest_validation_type": row.get("latest_validation_type", ""),
            "latest_validation_validator": row.get("latest_validation_validator", ""),
            "latest_validation_result": row.get("latest_validation_result", ""),
            "latest_validation_score": float(row.get("latest_validation_score") or 0.0),
            "latest_validation_message": row.get("latest_validation_message", ""),
            "latest_validation_detail_json": row.get("latest_validation_detail_json") or {},
            "latest_validation_at": str(row.get("latest_validation_at")).replace("+00:00", "Z")
            if row.get("latest_validation_at")
            else "",
            "latest_promotion_id": row.get("latest_promotion_id", ""),
            "target_table": row.get("latest_target_table", ""),
            "target_connection_id": row.get("latest_target_connection_id", ""),
            "connection_code": row.get("latest_connection_code", ""),
            "latest_promotion_result": row.get("latest_promotion_result", ""),
            "latest_promotion_message": row.get("latest_promotion_message", ""),
            "latest_promotion_at": str(row.get("latest_promotion_at")).replace("+00:00", "Z")
            if row.get("latest_promotion_at")
            else "",
            "created_at": str(row.get("created_at")).replace("+00:00", "Z") if row.get("created_at") else "",
            "updated_at": str(row.get("updated_at")).replace("+00:00", "Z") if row.get("updated_at") else "",
        }

    def _validate_unverified_connection(
        self,
        connection_row: Dict[str, Any],
        production_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        failed_fields: List[str] = []
        rule_checks: Dict[str, Any] = {}

        granularity = (connection_row.get("granularity") or "").strip().lower()
        modality = (connection_row.get("connection_modality") or "").strip().lower()
        source_ref = (connection_row.get("source_region_ref") or "").strip()
        target_ref = (connection_row.get("target_region_ref") or "").strip()
        en_name = (connection_row.get("en_name") or "").strip()
        cn_name = (connection_row.get("cn_name") or "").strip()
        alias_csv = (connection_row.get("alias") or "").strip()

        confidence_raw = connection_row.get("confidence")
        try:
            confidence = float(confidence_raw if confidence_raw is not None else 0.0)
        except Exception:
            confidence = -1.0

        if granularity not in GRANULARITY_ALLOWED:
            errors.append(f"invalid_granularity:{granularity or 'empty'}")
            failed_fields.append("granularity")
            rule_checks["granularity"] = {"ok": False, "allowed": sorted(GRANULARITY_ALLOWED), "value": granularity}
        else:
            rule_checks["granularity"] = {"ok": True, "value": granularity}

        if modality not in CONNECTION_MODALITY_ALLOWED:
            errors.append(f"invalid_connection_modality:{modality or 'empty'}")
            failed_fields.append("connection_modality")
            rule_checks["connection_modality"] = {"ok": False, "allowed": sorted(CONNECTION_MODALITY_ALLOWED), "value": modality}
        else:
            rule_checks["connection_modality"] = {"ok": True, "value": modality}

        if not source_ref:
            errors.append("missing_source_region_ref")
            failed_fields.append("source_region_ref")
        if not target_ref:
            errors.append("missing_target_region_ref")
            failed_fields.append("target_region_ref")
        if source_ref and target_ref and source_ref == target_ref:
            errors.append("source_target_same")
            failed_fields.extend(["source_region_ref", "target_region_ref"])
        rule_checks["source_target"] = {"ok": bool(source_ref and target_ref and source_ref != target_ref)}
        expected_prefix = {"major": "REG_MAJ_", "sub": "REG_SUB_", "allen": "REG_ALL_"}.get(granularity, "")
        if expected_prefix and source_ref and not source_ref.startswith(expected_prefix):
            errors.append(f"source_granularity_mismatch:{source_ref}")
            failed_fields.append("source_region_ref")
        if expected_prefix and target_ref and not target_ref.startswith(expected_prefix):
            errors.append(f"target_granularity_mismatch:{target_ref}")
            failed_fields.append("target_region_ref")
        if expected_prefix:
            rule_checks["granularity_route"] = {
                "ok": all(
                    not value or value.startswith(expected_prefix) for value in (source_ref, target_ref)
                ),
                "expected_prefix": expected_prefix,
            }

        if confidence < 0 or confidence > 1:
            errors.append(f"invalid_confidence:{confidence_raw}")
            failed_fields.append("confidence")
            rule_checks["confidence"] = {"ok": False, "value": confidence_raw}
        else:
            rule_checks["confidence"] = {"ok": True, "value": confidence}
        low_confidence = self._is_low_confidence(confidence)
        if low_confidence:
            warnings.append(f"low_confidence:{confidence}")
        rule_checks["confidence"]["low_confidence"] = low_confidence

        if not (en_name or cn_name):
            warnings.append("missing_connection_name")
            rule_checks["name"] = {"ok": False}
        else:
            rule_checks["name"] = {"ok": True}

        if granularity in GRANULARITY_ALLOWED and source_ref and target_ref:
            table, id_col = self._region_table_for_connection_granularity(granularity)
            prod_schema = production_cfg.get("schema", "neurokg")
            prod_db = self._db_cfg(production_cfg)
            with psycopg.connect(**prod_db, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"select 1 from {prod_schema}.{table} where {id_col}=%s", (source_ref,))
                    if not cur.fetchone():
                        errors.append(f"source_region_not_found:{source_ref}")
                        failed_fields.append("source_region_ref")

                    cur.execute(f"select 1 from {prod_schema}.{table} where {id_col}=%s", (target_ref,))
                    if not cur.fetchone():
                        errors.append(f"target_region_not_found:{target_ref}")
                        failed_fields.append("target_region_ref")

                    main_table, _, _, _ = self._connection_main_table(granularity)
                    if en_name:
                        cur.execute(
                            f"select 1 from {prod_schema}.{main_table} where lower(en_name)=%s limit 1",
                            (en_name.lower(),),
                        )
                        if cur.fetchone():
                            warnings.append("duplicate_connection_en_name_in_final")
                    if cn_name:
                        cur.execute(
                            f"select 1 from {prod_schema}.{main_table} where lower(cn_name)=%s limit 1",
                            (cn_name.lower(),),
                        )
                        if cur.fetchone():
                            warnings.append("duplicate_connection_cn_name_in_final")
                    aliases = [x.strip() for x in alias_csv.split(",") if x.strip()]
                    if aliases:
                        cur.execute(
                            f"select 1 from {prod_schema}.{main_table} where alias && %s::text[] limit 1",
                            (aliases,),
                        )
                        if cur.fetchone():
                            warnings.append("duplicate_connection_alias_in_final")

        uv_cfg = production_cfg.get("_unverified_ref", {})
        if uv_cfg:
            uv_schema = uv_cfg.get("schema", "neurokg_unverified")
            uv_db = self._db_cfg(uv_cfg)
            try:
                with psycopg.connect(**uv_db, row_factory=dict_row) as uconn:
                    with uconn.cursor() as ucur:
                        ucur.execute(
                            f"""
                            select id, en_name, cn_name, alias
                            from {uv_schema}.unverified_connection
                            where id<>%s
                              and granularity=%s
                              and source_region_ref=%s
                              and target_region_ref=%s
                              and connection_modality=%s
                            order by created_at desc
                            limit 5
                            """,
                            (
                                connection_row.get("id", ""),
                                granularity,
                                source_ref,
                                target_ref,
                                modality,
                            ),
                        )
                        for other in ucur.fetchall():
                            warnings.append(f"duplicate_connection_pattern_in_unverified:{other.get('id','')}")
            except Exception as exc:
                warnings.append(f"unverified_duplicate_check_failed:{exc}")

        evidence_check = self._validate_evidence_items(connection_row.get("evidence_json"), entity="connection")
        if evidence_check["errors"]:
            errors.extend(evidence_check["errors"])
            failed_fields.extend(["evidence_type"])
        if evidence_check["warnings"]:
            warnings.extend(evidence_check["warnings"])
        rule_checks["evidence"] = evidence_check["rule_checks"]

        if warnings:
            rule_checks["duplicates"] = {"ok": True, "warnings": warnings}
        rule_summary = self._build_rule_summary(errors, warnings, rule_checks, failed_fields)
        return {
            "errors": errors,
            "warnings": warnings,
            "failed_fields": list(dict.fromkeys(failed_fields)),
            "rule_checks": rule_checks,
            "rule_summary": rule_summary,
            "low_confidence": low_confidence,
        }

    def _validate_unverified_circuit(
        self,
        circuit_row: Dict[str, Any],
        nodes: List[Dict[str, Any]],
        production_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        failed_fields: List[str] = []
        rule_checks: Dict[str, Any] = {}

        granularity = (circuit_row.get("granularity") or "").strip().lower()
        circuit_kind = (circuit_row.get("circuit_kind") or "").strip().lower()
        loop_type = (circuit_row.get("loop_type") or "").strip().lower()
        en_name = (circuit_row.get("en_name") or "").strip()
        cn_name = (circuit_row.get("cn_name") or "").strip()
        alias_csv = (circuit_row.get("alias") or "").strip()

        if granularity not in GRANULARITY_ALLOWED:
            errors.append(f"invalid_granularity:{granularity or 'empty'}")
            failed_fields.append("granularity")
            rule_checks["granularity"] = {"ok": False, "allowed": sorted(GRANULARITY_ALLOWED), "value": granularity}
        else:
            rule_checks["granularity"] = {"ok": True, "value": granularity}

        if circuit_kind not in CIRCUIT_KIND_ALLOWED:
            errors.append(f"invalid_circuit_kind:{circuit_kind or 'empty'}")
            failed_fields.append("circuit_kind")
            rule_checks["circuit_kind"] = {"ok": False, "allowed": sorted(CIRCUIT_KIND_ALLOWED), "value": circuit_kind}
        else:
            rule_checks["circuit_kind"] = {"ok": True, "value": circuit_kind}

        if loop_type not in LOOP_TYPE_ALLOWED:
            errors.append(f"invalid_loop_type:{loop_type or 'empty'}")
            failed_fields.append("loop_type")
            rule_checks["loop_type"] = {"ok": False, "allowed": sorted(LOOP_TYPE_ALLOWED), "value": loop_type}
        else:
            rule_checks["loop_type"] = {"ok": True, "value": loop_type}

        if not (en_name or cn_name):
            errors.append("missing_circuit_name")
            failed_fields.append("en_name_or_cn_name")
            rule_checks["name"] = {"ok": False}
        else:
            rule_checks["name"] = {"ok": True}
        confidence_raw = circuit_row.get("confidence_circuit")
        try:
            confidence = float(confidence_raw if confidence_raw is not None else 0.0)
        except Exception:
            confidence = -1.0
        low_confidence = self._is_low_confidence(confidence)
        if low_confidence:
            warnings.append(f"low_confidence:{confidence}")
        rule_checks["confidence_circuit"] = {"ok": confidence >= 0, "value": confidence_raw, "low_confidence": low_confidence}

        if not nodes:
            errors.append("missing_circuit_nodes")
            failed_fields.append("nodes")
            rule_checks["node_count"] = {"ok": False, "value": 0}
        else:
            rule_checks["node_count"] = {"ok": len(nodes) >= 1, "value": len(nodes)}
            seen_orders: set[int] = set()
            for idx, n in enumerate(nodes, start=1):
                order = int(n.get("node_order") or 0)
                region_id = (n.get("region_id_ref") or "").strip()
                node_granularity = (n.get("granularity") or "").strip().lower()
                if order <= 0:
                    errors.append(f"invalid_node_order:index_{idx}")
                    failed_fields.append("node_order")
                elif order in seen_orders:
                    errors.append(f"duplicate_node_order:{order}")
                    failed_fields.append("node_order")
                seen_orders.add(order)
                if not region_id:
                    errors.append(f"missing_node_region_id:index_{idx}")
                    failed_fields.append("node.region_id")
                if node_granularity and node_granularity != granularity:
                    errors.append(f"node_granularity_mismatch:index_{idx}")
                    failed_fields.append("node.granularity")

        # duplicate hints in unverified/final by same granularity and names
        try:
            uv_cfg = production_cfg.get("_unverified_ref", {})
            if uv_cfg:
                with psycopg.connect(**self._db_cfg(uv_cfg), row_factory=dict_row) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"select id from {uv_cfg.get('schema','neurokg_unverified')}.unverified_circuit where id<>%s and granularity=%s and lower(coalesce(en_name,''))=%s limit 1",
                            (circuit_row.get("id", ""), granularity, en_name.lower()),
                        )
                        if en_name and cur.fetchone():
                            warnings.append("duplicate_circuit_en_name_in_unverified")
        except Exception:
            pass

        if granularity in GRANULARITY_ALLOWED and nodes:
            table, id_col = self._region_table_for_circuit_granularity(granularity)
            prod_schema = production_cfg.get("schema", "neurokg")
            prod_db = self._db_cfg(production_cfg)
            with psycopg.connect(**prod_db, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    for idx, n in enumerate(nodes, start=1):
                        region_id = (n.get("region_id_ref") or "").strip()
                        if not region_id:
                            continue
                        cur.execute(f"select 1 from {prod_schema}.{table} where {id_col}=%s", (region_id,))
                        if not cur.fetchone():
                            errors.append(f"region_not_found_for_node:index_{idx}:{region_id}")
                            failed_fields.append("node.region_id")

                    if en_name:
                        cur.execute(
                            f"select 1 from {prod_schema}.{self._circuit_main_table(granularity)[0]} where lower(en_name)=%s limit 1",
                            (en_name.lower(),),
                        )
                        if cur.fetchone():
                            warnings.append("duplicate_circuit_en_name_in_final")
                    if cn_name:
                        cur.execute(
                            f"select 1 from {prod_schema}.{self._circuit_main_table(granularity)[0]} where lower(cn_name)=%s limit 1",
                            (cn_name.lower(),),
                        )
                        if cur.fetchone():
                            warnings.append("duplicate_circuit_cn_name_in_final")
                    aliases = [x.strip() for x in alias_csv.split(",") if x.strip()]
                    if aliases:
                        cur.execute(
                            f"select 1 from {prod_schema}.{self._circuit_main_table(granularity)[0]} where alias && %s::text[] limit 1",
                            (aliases,),
                        )
                        if cur.fetchone():
                            warnings.append("duplicate_circuit_alias_in_final")

        if granularity in GRANULARITY_ALLOWED and nodes:
            uv_cfg = production_cfg.get("_unverified_ref", {})
            if uv_cfg:
                uv_schema = uv_cfg.get("schema", "neurokg_unverified")
                uv_db = self._db_cfg(uv_cfg)
                node_sig = "|".join(
                    sorted(
                        f"{(n.get('region_id_ref') or '').strip()}:{int(n.get('node_order') or 0)}"
                        for n in nodes
                    )
                )
                try:
                    with psycopg.connect(**uv_db, row_factory=dict_row) as uconn:
                        with uconn.cursor() as ucur:
                            ucur.execute(
                                f"""
                                select c.id as circuit_id,
                                       string_agg(n.region_id_ref || ':' || n.node_order::text, '|' order by n.region_id_ref, n.node_order) as node_sig
                                from {uv_schema}.unverified_circuit c
                                join {uv_schema}.unverified_circuit_node n on n.unverified_circuit_id=c.id
                                where c.id<>%s and c.granularity=%s
                                group by c.id
                                order by c.created_at desc
                                limit 30
                                """,
                                (circuit_row.get("id", ""), granularity),
                            )
                            for other in ucur.fetchall():
                                if (other.get("node_sig") or "") == node_sig:
                                    warnings.append(f"duplicate_circuit_nodes_in_unverified:{other.get('circuit_id','')}")
                except Exception as exc:
                    warnings.append(f"unverified_circuit_duplicate_check_failed:{exc}")

        evidence_check = self._validate_evidence_items(circuit_row.get("evidence_json"), entity="circuit")
        if evidence_check["errors"]:
            errors.extend(evidence_check["errors"])
            failed_fields.extend(["evidence_type"])
        if evidence_check["warnings"]:
            warnings.extend(evidence_check["warnings"])
        rule_checks["evidence"] = evidence_check["rule_checks"]

        if warnings:
            rule_checks["duplicates"] = {"ok": True, "warnings": warnings}
        rule_summary = self._build_rule_summary(errors, warnings, rule_checks, failed_fields)
        return {
            "errors": errors,
            "warnings": warnings,
            "failed_fields": list(dict.fromkeys(failed_fields)),
            "rule_checks": rule_checks,
            "rule_summary": rule_summary,
            "low_confidence": low_confidence,
        }

    @staticmethod
    def _circuit_main_table(granularity: str) -> Tuple[str, str]:
        if granularity == "major":
            return "major_circuit", "major_circuit_id"
        if granularity == "sub":
            return "sub_circuit", "sub_circuit_id"
        return "allen_circuit", "allen_circuit_id"

    @staticmethod
    def _circuit_node_table(granularity: str) -> Tuple[str, str]:
        if granularity == "major":
            return "major_circuit_node", "major_region_id"
        if granularity == "sub":
            return "sub_circuit_node", "sub_region_id"
        return "allen_circuit_node", "allen_region_id"

    @staticmethod
    def _region_table_for_circuit_granularity(granularity: str) -> Tuple[str, str]:
        if granularity == "major":
            return "major_brain_region", "major_region_id"
        if granularity == "sub":
            return "sub_brain_region", "sub_region_id"
        return "allen_brain_region", "allen_region_id"

    @staticmethod
    def _connection_main_table(granularity: str) -> Tuple[str, str, str, str]:
        if granularity == "major":
            return "major_connection", "major_connection_id", "source_major_region_id", "target_major_region_id"
        if granularity == "sub":
            return "sub_connection", "sub_connection_id", "source_sub_region_id", "target_sub_region_id"
        return "allen_connection", "allen_connection_id", "source_allen_region_id", "target_allen_region_id"

    @staticmethod
    def _region_table_for_connection_granularity(granularity: str) -> Tuple[str, str]:
        if granularity == "major":
            return "major_brain_region", "major_region_id"
        if granularity == "sub":
            return "sub_brain_region", "sub_region_id"
        return "allen_brain_region", "allen_region_id"

    def _generate_connection_id(
        self,
        cur: psycopg.Cursor,
        schema: str,
        table: str,
        id_col: str,
        granularity: str,
    ) -> str:
        prefix = {"major": "MAJOR_CONN", "sub": "SUB_CONN", "allen": "ALLEN_CONN"}.get(granularity, "CONN")
        for _ in range(8):
            candidate = f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            cur.execute(f"select 1 from {schema}.{table} where {id_col}=%s", (candidate,))
            if not cur.fetchone():
                return candidate
        return _make_id("conn")

    def _generate_connection_code(
        self,
        cur: psycopg.Cursor,
        schema: str,
        table: str,
        granularity: str,
    ) -> str:
        code_prefix = {"major": "MC", "sub": "SC", "allen": "AC"}.get(granularity, "CC")
        for _ in range(8):
            candidate = f"{code_prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5].upper()}"
            cur.execute(f"select 1 from {schema}.{table} where connection_code=%s", (candidate,))
            if not cur.fetchone():
                return candidate
        return f"{code_prefix}_{uuid.uuid4().hex[:10].upper()}"

    def _commit_one_circuit(
        self,
        cur: psycopg.Cursor,
        schema: str,
        circuit_row: Dict[str, Any],
        nodes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        granularity = (circuit_row.get("granularity") or "").strip().lower()
        if granularity not in GRANULARITY_ALLOWED:
            raise ValueError(f"invalid_granularity:{granularity or 'empty'}")
        table, id_col = self._circuit_main_table(granularity)
        node_table, node_region_col = self._circuit_node_table(granularity)

        circuit_id = self._circuit_identity.generate_circuit_id(cur, schema, table, id_col, granularity, circuit_row)
        circuit_code = self._circuit_identity.generate_circuit_code(cur, schema, table, circuit_row)
        aliases = [x.strip() for x in (circuit_row.get("alias") or "").split(",") if x.strip()]
        now = datetime.now(timezone.utc)
        payload = {
            id_col: circuit_id,
            "circuit_code": circuit_code,
            "en_name": (circuit_row.get("en_name") or "").strip(),
            "cn_name": (circuit_row.get("cn_name") or "").strip(),
            "alias": aliases,
            "description": (circuit_row.get("description") or "").strip(),
            "circuit_kind": (circuit_row.get("circuit_kind") or "unknown").strip().lower(),
            "loop_type": (circuit_row.get("loop_type") or "inferred").strip().lower(),
            "cycle_verified": bool(circuit_row.get("cycle_verified", False)),
            "confidence_circuit": float(circuit_row.get("confidence_circuit") or 0.0),
            "validation_status_circuit": "passed",
            "node_count": len(nodes),
            "connection_count": 0,
            "data_source": (circuit_row.get("data_source") or "").strip(),
            "status": "active",
            "remark": f"unverified_circuit_id={circuit_row.get('id','')};source_candidate={circuit_row.get('source_candidate_circuit_id','')}",
            "created_at": now,
            "updated_at": now,
        }
        cols = self._columns(cur, schema, table)
        missing = [k for k in payload.keys() if k not in cols]
        if missing:
            raise ValueError(f"target_table_missing_columns:{','.join(missing)}")
        cur.execute(
            f"insert into {schema}.{table} ({', '.join(payload.keys())}) values ({', '.join([f'%({k})s' for k in payload.keys()])})",
            payload,
        )
        for n in nodes:
            node_payload = {
                id_col: circuit_id,
                node_region_col: (n.get("region_id_ref") or "").strip(),
                "node_order": int(n.get("node_order")) if n.get("node_order") is not None else 1,
                "role_label": (n.get("role_label") or "").strip(),
                "created_at": now,
            }
            node_cols = self._columns(cur, schema, node_table)
            node_missing = [k for k in node_payload.keys() if k not in node_cols]
            if node_missing:
                raise ValueError(f"target_node_table_missing_columns:{','.join(node_missing)}")
            cur.execute(
                f"insert into {schema}.{node_table} ({', '.join(node_payload.keys())}) values ({', '.join([f'%({k})s' for k in node_payload.keys()])})",
                node_payload,
            )

        evidence_result = self._resolve_and_attach_evidence(
            cur=cur,
            schema=schema,
            granularity=granularity,
            entity_kind="circuit",
            target_id=circuit_id,
            evidence_items=self._extract_evidence_payload(circuit_row, {}),
            source_file_id=(circuit_row.get("source_file_id") or "").strip(),
            source_task_id=(circuit_row.get("source_candidate_circuit_id") or "").strip(),
        )

        return {
            "target_table": f"{schema}.{table}",
            "primary_key": circuit_id,
            "circuit_code": circuit_code,
            "id_column": id_col,
            "table": table,
            "node_table": node_table,
            "granularity": granularity,
            "evidence": evidence_result,
        }

    def _commit_one_connection(
        self,
        cur: psycopg.Cursor,
        schema: str,
        connection_row: Dict[str, Any],
    ) -> Dict[str, Any]:
        granularity = (connection_row.get("granularity") or "").strip().lower()
        if granularity not in GRANULARITY_ALLOWED:
            raise ValueError(f"invalid_granularity:{granularity or 'empty'}")
        modality = (connection_row.get("connection_modality") or "").strip().lower()
        if modality not in CONNECTION_MODALITY_ALLOWED:
            raise ValueError(f"invalid_connection_modality:{modality or 'empty'}")

        source_ref = (connection_row.get("source_region_ref") or "").strip()
        target_ref = (connection_row.get("target_region_ref") or "").strip()
        if not source_ref:
            raise ValueError("missing_source_region_ref")
        if not target_ref:
            raise ValueError("missing_target_region_ref")
        if source_ref == target_ref:
            raise ValueError("source_target_same")

        try:
            confidence = float(connection_row.get("confidence") if connection_row.get("confidence") is not None else 0.0)
        except Exception:
            confidence = -1.0
        if confidence < 0 or confidence > 1:
            raise ValueError(f"invalid_confidence:{connection_row.get('confidence')}")

        table, id_col, source_col, target_col = self._connection_main_table(granularity)
        region_table, region_id_col = self._region_table_for_connection_granularity(granularity)
        cur.execute(f"select 1 from {schema}.{region_table} where {region_id_col}=%s", (source_ref,))
        if not cur.fetchone():
            raise ValueError(f"source_region_not_found:{source_ref}")
        cur.execute(f"select 1 from {schema}.{region_table} where {region_id_col}=%s", (target_ref,))
        if not cur.fetchone():
            raise ValueError(f"target_region_not_found:{target_ref}")

        connection_id = self._generate_connection_id(cur, schema, table, id_col, granularity)
        connection_code = self._generate_connection_code(cur, schema, table, granularity)
        aliases = [x.strip() for x in (connection_row.get("alias") or "").split(",") if x.strip()]
        now = datetime.now(timezone.utc)
        payload = {
            id_col: connection_id,
            "connection_code": connection_code,
            "en_name": (connection_row.get("en_name") or "").strip(),
            "cn_name": (connection_row.get("cn_name") or "").strip(),
            "alias": aliases,
            "description": (connection_row.get("description") or "").strip(),
            "connection_modality": modality,
            source_col: source_ref,
            target_col: target_ref,
            "confidence": confidence,
            "validation_status": "passed",
            "direction_label": (connection_row.get("direction_label") or "unknown").strip().lower(),
            "extraction_method": (connection_row.get("extraction_method") or "unverified_promote").strip(),
            "data_source": (connection_row.get("data_source") or "").strip(),
            "status": "active",
            "remark": f"unverified_connection_id={connection_row.get('id','')};source_candidate={connection_row.get('source_candidate_connection_id','')}",
            "created_at": now,
            "updated_at": now,
        }
        cols = self._columns(cur, schema, table)
        missing = [k for k in payload.keys() if k not in cols]
        if missing:
            raise ValueError(f"target_table_missing_columns:{','.join(missing)}")

        cur.execute(
            f"insert into {schema}.{table} ({', '.join(payload.keys())}) values ({', '.join([f'%({k})s' for k in payload.keys()])}) returning {id_col}, connection_code",
            payload,
        )
        inserted = cur.fetchone()
        evidence_result = self._resolve_and_attach_evidence(
            cur=cur,
            schema=schema,
            granularity=granularity,
            entity_kind="connection",
            target_id=inserted[id_col],
            evidence_items=self._extract_evidence_payload(connection_row, {}),
            source_file_id=(connection_row.get("source_file_id") or "").strip(),
            source_task_id=(connection_row.get("source_candidate_connection_id") or "").strip(),
        )
        return {
            "target_table": f"{schema}.{table}",
            "primary_key": inserted[id_col],
            "connection_code": inserted["connection_code"],
            "id_column": id_col,
            "table": table,
            "granularity": granularity,
            "evidence": evidence_result,
        }

    @staticmethod
    def _promotion_circuit_error_detail(reason: str) -> Dict[str, Any]:
        failed_map = {
            "invalid_granularity": ["granularity"],
            "invalid_circuit_kind": ["circuit_kind"],
            "invalid_loop_type": ["loop_type"],
            "missing_circuit_nodes": ["nodes"],
            "invalid_node_order": ["node_order"],
            "duplicate_node_order": ["node_order"],
            "missing_node_region_id": ["node.region_id"],
            "region_not_found_for_node": ["node.region_id"],
            "node_granularity_mismatch": ["node.granularity"],
            "target_table_missing_columns": ["target_table_columns"],
            "target_node_table_missing_columns": ["target_node_table_columns"],
            "invalid_evidence_type": ["evidence_type"],
            "evidence_attach_columns_missing": ["evidence_attach_columns"],
        }
        code = reason.split(":", 1)[0]
        return {
            "code": code,
            "message": reason,
            "failed_fields": failed_map.get(code, []),
            "rule_checks": {},
        }

    @staticmethod
    def _promotion_connection_error_detail(reason: str) -> Dict[str, Any]:
        failed_map = {
            "invalid_granularity": ["granularity"],
            "invalid_connection_modality": ["connection_modality"],
            "missing_source_region_ref": ["source_region_ref"],
            "missing_target_region_ref": ["target_region_ref"],
            "source_target_same": ["source_region_ref", "target_region_ref"],
            "source_region_not_found": ["source_region_ref"],
            "target_region_not_found": ["target_region_ref"],
            "invalid_confidence": ["confidence"],
            "target_table_missing_columns": ["target_table_columns"],
            "invalid_evidence_type": ["evidence_type"],
            "evidence_attach_columns_missing": ["evidence_attach_columns"],
        }
        code = reason.split(":", 1)[0]
        return {
            "code": code,
            "message": reason,
            "failed_fields": failed_map.get(code, []),
            "rule_checks": {},
        }

    def _extract_evidence_payload(self, row: Dict[str, Any], file_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = row.get("evidence_json")
        if isinstance(raw, str):
            try:
                import json

                raw = json.loads(raw)
            except Exception:
                raw = []
        if isinstance(raw, list):
            out = [x for x in raw if isinstance(x, dict)]
            if out:
                return out
        source_text = (row.get("source_text") or row.get("description") or "").strip()
        source_title = (row.get("source_title") or file_payload.get("filename") or "").strip()
        if not (source_text or source_title):
            return []
        return [
            {
                "evidence_text": source_text[:2000],
                "source_title": source_title[:300],
                "pmid": (row.get("pmid") or "").strip(),
                "doi": (row.get("doi") or "").strip(),
                "section": (row.get("section") or "").strip(),
                "publication_year": row.get("publication_year"),
                "journal": (row.get("journal") or "").strip(),
                "evidence_type": (row.get("evidence_type") or "manual_note").strip().lower(),
                "data_source": (row.get("data_source") or file_payload.get("filename") or "").strip(),
                "en_name": (row.get("en_name") or "").strip(),
                "cn_name": (row.get("cn_name") or "").strip(),
                "alias": row.get("alias") or "",
                "description": (row.get("description") or "").strip(),
            }
        ]

    def _validate_evidence_items(self, evidence_json: Any, entity: str) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        rule_checks: Dict[str, Any] = {"entity": entity, "count": 0, "items": []}
        items = evidence_json
        if isinstance(items, str):
            try:
                import json

                items = json.loads(items)
            except Exception:
                items = []
        if not isinstance(items, list):
            return {"errors": [], "warnings": [], "rule_checks": {"entity": entity, "count": 0, "items": []}}
        rule_checks["count"] = len(items)
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                warnings.append(f"evidence_item_invalid_type:index_{idx}")
                continue
            evidence_type = (item.get("evidence_type") or "manual_note").strip().lower()
            item_check = {"index": idx, "evidence_type": evidence_type, "ok": True}
            if evidence_type not in EVIDENCE_TYPE_ALLOWED:
                errors.append(f"invalid_evidence_type:index_{idx}:{evidence_type or 'empty'}")
                item_check["ok"] = False
            if not ((item.get("doi") or "").strip() or (item.get("pmid") or "").strip() or (item.get("source_title") or "").strip()):
                warnings.append(f"evidence_missing_identifier:index_{idx}")
            rule_checks["items"].append(item_check)
        return {"errors": errors, "warnings": warnings, "rule_checks": rule_checks}

    @staticmethod
    def _is_low_confidence(value: float, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> bool:
        return value >= 0 and value < threshold

    def _build_rule_summary(
        self,
        errors: List[str],
        warnings: List[str],
        rule_checks: Dict[str, Any],
        failed_fields: List[str],
    ) -> Dict[str, Any]:
        duplicate_hits = [w for w in warnings if "duplicate" in w or "weak_match" in w]
        conflict_tokens = ("mismatch", "conflict", "source_target_same", "parent", "not_found", "invalid_")
        conflict_hits = [e for e in errors if any(token in e for token in conflict_tokens)]
        failed_rules = [
            key for key, value in rule_checks.items() if isinstance(value, dict) and value.get("ok") is False
        ]
        return {
            "status": "failed" if errors else ("warning" if warnings else "passed"),
            "blocking_errors": errors,
            "warning_hits": warnings,
            "duplicate_hits": duplicate_hits,
            "conflict_hits": conflict_hits,
            "failed_fields": list(dict.fromkeys(failed_fields)),
            "failed_rules": failed_rules,
            "has_conflict": bool(conflict_hits),
            "has_duplicate_hint": bool(duplicate_hits),
        }

    def _resolve_and_attach_evidence(
        self,
        cur: psycopg.Cursor,
        schema: str,
        granularity: str,
        entity_kind: str,
        target_id: str,
        evidence_items: List[Dict[str, Any]],
        source_file_id: str,
        source_task_id: str,
    ) -> Dict[str, Any]:
        events: List[Dict[str, Any]] = []
        if not evidence_items:
            return {
                "attached_count": 0,
                "reused_count": 0,
                "created_count": 0,
                "weak_match_hints": [],
                "events": events,
                "items": [],
            }
        cols = self._columns(cur, schema, "evidence")
        id_col = "evidence_id" if "evidence_id" in cols else "id"
        attached_count = 0
        reused_count = 0
        created_count = 0
        weak_match_hints: List[Dict[str, Any]] = []
        item_results: List[Dict[str, Any]] = []
        for idx, raw in enumerate(evidence_items):
            item = raw if isinstance(raw, dict) else {}
            evidence_type = (item.get("evidence_type") or "manual_note").strip().lower()
            if evidence_type not in EVIDENCE_TYPE_ALLOWED:
                raise ValueError(f"invalid_evidence_type:index_{idx}:{evidence_type or 'empty'}")
            doi = (item.get("doi") or "").strip()
            pmid = (item.get("pmid") or "").strip()
            source_title = (item.get("source_title") or "").strip()
            publication_year = item.get("publication_year")
            events.append(
                {
                    "event_type": "evidence_lookup_started",
                    "message": f"evidence_lookup_started entity={entity_kind} target_id={target_id} index={idx}",
                    "detail": {"idx": idx, "doi": doi, "pmid": pmid, "title": source_title, "publication_year": publication_year},
                }
            )
            matched = self._find_existing_evidence(cur, schema, cols, id_col, doi, pmid, source_title, publication_year)
            evidence_id = ""
            reuse_reason = ""
            if matched.get("exact"):
                evidence_id = matched.get("evidence_id", "")
                reuse_reason = matched.get("reason", "exact")
                reused_count += 1
                events.append(
                    {
                        "event_type": "evidence_lookup_succeeded",
                        "message": f"evidence_lookup_succeeded entity={entity_kind} index={idx} reason={reuse_reason}",
                        "detail": {"idx": idx, "reason": reuse_reason, "evidence_id": evidence_id},
                    }
                )
                events.append(
                    {
                        "event_type": "evidence_reused",
                        "message": f"evidence_reused entity={entity_kind} index={idx} evidence_id={evidence_id}",
                        "detail": {"idx": idx, "evidence_id": evidence_id, "reason": reuse_reason},
                    }
                )
            else:
                if matched.get("weak_match"):
                    weak_match_hints.append(
                        {
                            "idx": idx,
                            "suggested_evidence_id": matched.get("evidence_id", ""),
                            "reason": matched.get("reason", "title_year"),
                        }
                    )
                    events.append(
                        {
                            "event_type": "evidence_lookup_succeeded",
                            "message": f"evidence_lookup_succeeded entity={entity_kind} index={idx} reason=weak_title_year",
                            "detail": {
                                "idx": idx,
                                "reason": "weak_title_year",
                                "suggested_evidence_id": matched.get("evidence_id", ""),
                            },
                        }
                    )
                try:
                    evidence_id = self._insert_evidence(
                        cur=cur,
                        schema=schema,
                        cols=cols,
                        id_col=id_col,
                        item=item,
                        source_file_id=source_file_id,
                        source_task_id=source_task_id,
                    )
                    created_count += 1
                    events.append(
                        {
                            "event_type": "evidence_created",
                            "message": f"evidence_created entity={entity_kind} index={idx} evidence_id={evidence_id}",
                            "detail": {"idx": idx, "evidence_id": evidence_id},
                        }
                    )
                except Exception as exc:
                    events.append(
                        {
                            "event_type": "evidence_lookup_failed",
                            "message": f"evidence_lookup_failed entity={entity_kind} index={idx} reason={exc}",
                            "detail": {"idx": idx, "error": str(exc)},
                        }
                    )
                    raise
            self._attach_entity_evidence(cur, schema, entity_kind, granularity, target_id, evidence_id)
            attached_count += 1
            item_results.append(
                {
                    "idx": idx,
                    "evidence_id": evidence_id,
                    "mode": "reused" if reuse_reason else "created",
                    "reuse_reason": reuse_reason,
                }
            )
        return {
            "attached_count": attached_count,
            "reused_count": reused_count,
            "created_count": created_count,
            "weak_match_hints": weak_match_hints,
            "events": events,
            "items": item_results,
        }

    def _find_existing_evidence(
        self,
        cur: psycopg.Cursor,
        schema: str,
        cols: set[str],
        id_col: str,
        doi: str,
        pmid: str,
        source_title: str,
        publication_year: Any,
    ) -> Dict[str, Any]:
        order_col = "created_at" if "created_at" in cols else id_col
        if doi and "doi" in cols:
            cur.execute(
                f"select {id_col} as evidence_id from {schema}.evidence where lower(coalesce(doi,''))=%s order by {order_col} desc limit 1",
                (doi.lower(),),
            )
            row = cur.fetchone()
            if row:
                return {"exact": True, "evidence_id": row.get("evidence_id", ""), "reason": "doi"}
        if pmid and "pmid" in cols:
            cur.execute(
                f"select {id_col} as evidence_id from {schema}.evidence where lower(coalesce(pmid,''))=%s order by {order_col} desc limit 1",
                (pmid.lower(),),
            )
            row = cur.fetchone()
            if row:
                return {"exact": True, "evidence_id": row.get("evidence_id", ""), "reason": "pmid"}
        if source_title and publication_year not in (None, "") and "source_title" in cols and "publication_year" in cols:
            try:
                pub_year = int(publication_year)
            except Exception:
                pub_year = None
            if pub_year is not None:
                cur.execute(
                    f"""
                    select {id_col} as evidence_id
                    from {schema}.evidence
                    where lower(coalesce(source_title,''))=%s and publication_year=%s
                    order by {order_col} desc
                    limit 1
                    """,
                    (source_title.lower(), pub_year),
                )
                row = cur.fetchone()
                if row:
                    return {"exact": False, "weak_match": True, "evidence_id": row.get("evidence_id", ""), "reason": "title_year"}
        return {"exact": False, "weak_match": False, "evidence_id": "", "reason": ""}

    def _insert_evidence(
        self,
        cur: psycopg.Cursor,
        schema: str,
        cols: set[str],
        id_col: str,
        item: Dict[str, Any],
        source_file_id: str,
        source_task_id: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {}
        evidence_id = ""
        if id_col == "evidence_id":
            evidence_id = self._generate_evidence_id(cur, schema, "evidence")
            payload["evidence_id"] = evidence_id
        elif id_col == "id":
            evidence_id = ""
        alias_is_array = self._is_array_column(cur, schema, "evidence", "alias")
        evidence_code = self._generate_evidence_code(cur, schema, "evidence") if "evidence_code" in cols else ""
        payload.update(
            {
                "evidence_code": evidence_code,
                "en_name": (item.get("en_name") or "").strip(),
                "cn_name": (item.get("cn_name") or "").strip(),
                "alias": self._normalize_alias_value(item.get("alias"), alias_is_array),
                "description": (item.get("description") or "").strip(),
                "evidence_text": (item.get("evidence_text") or "").strip(),
                "source_title": (item.get("source_title") or "").strip(),
                "pmid": (item.get("pmid") or "").strip(),
                "doi": (item.get("doi") or "").strip(),
                "section": (item.get("section") or "").strip(),
                "publication_year": self._safe_int(item.get("publication_year")),
                "journal": (item.get("journal") or "").strip(),
                "evidence_type": (item.get("evidence_type") or "manual_note").strip().lower(),
                "data_source": (item.get("data_source") or "").strip(),
                "status": "active",
                "remark": "created_by_workbench_promote",
                "created_at": now,
                "updated_at": now,
                "source_file_id": source_file_id,
                "source_task_id": source_task_id,
            }
        )
        insert_payload = {k: v for k, v in payload.items() if k in cols and not (k == "publication_year" and v is None)}
        if "evidence_text" in cols and not insert_payload.get("evidence_text"):
            insert_payload["evidence_text"] = (insert_payload.get("source_title") or "").strip()
        if not insert_payload.get("evidence_text"):
            insert_payload["evidence_text"] = "n/a"

        column_names = list(insert_payload.keys())
        values_sql = []
        for key in column_names:
            if key == "alias" and "alias" in cols and isinstance(insert_payload.get("alias"), list):
                values_sql.append(f"%({key})s")
            else:
                values_sql.append(f"%({key})s")
        returning_sql = f" returning {id_col}" if id_col in cols else ""
        cur.execute(
            f"insert into {schema}.evidence ({', '.join(column_names)}) values ({', '.join(values_sql)}){returning_sql}",
            insert_payload,
        )
        if id_col in cols:
            row = cur.fetchone()
            if row and row.get(id_col) is not None:
                return str(row.get(id_col))
        # fallback for tables using serial id without returning
        order_col = "created_at" if "created_at" in cols else id_col
        cur.execute(f"select {id_col} as evidence_id from {schema}.evidence order by {order_col} desc limit 1")
        row = cur.fetchone()
        return str(row.get("evidence_id")) if row else evidence_id

    def _attach_entity_evidence(
        self,
        cur: psycopg.Cursor,
        schema: str,
        entity_kind: str,
        granularity: str,
        target_id: str,
        evidence_id: str,
    ) -> None:
        table, target_col = self._evidence_attach_table(entity_kind, granularity)
        cols = self._columns(cur, schema, table)
        payload: Dict[str, Any] = {}
        if target_col in cols:
            payload[target_col] = target_id
        if "evidence_id" in cols:
            payload["evidence_id"] = evidence_id
        if "status" in cols:
            payload["status"] = "active"
        if "remark" in cols:
            payload["remark"] = "evidence_linked_by_promote"
        if "created_at" in cols:
            payload["created_at"] = datetime.now(timezone.utc)
        if len(payload) < 2:
            raise ValueError(f"evidence_attach_columns_missing:{table}")
        where_sql = []
        where_params: List[Any] = []
        if target_col in payload:
            where_sql.append(f"{target_col}=%s")
            where_params.append(payload[target_col])
        if "evidence_id" in payload:
            where_sql.append("evidence_id=%s")
            where_params.append(payload["evidence_id"])
        if where_sql:
            cur.execute(f"select 1 from {schema}.{table} where {' and '.join(where_sql)} limit 1", tuple(where_params))
            if cur.fetchone():
                return
        col_sql = ", ".join(payload.keys())
        val_sql = ", ".join([f"%({k})s" for k in payload.keys()])
        cur.execute(f"insert into {schema}.{table} ({col_sql}) values ({val_sql})", payload)

    @staticmethod
    def _evidence_attach_table(entity_kind: str, granularity: str) -> Tuple[str, str]:
        if entity_kind == "connection":
            if granularity == "major":
                return "major_connection_evidence", "major_connection_id"
            if granularity == "sub":
                return "sub_connection_evidence", "sub_connection_id"
            return "allen_connection_evidence", "allen_connection_id"
        if granularity == "major":
            return "major_circuit_evidence", "major_circuit_id"
        if granularity == "sub":
            return "sub_circuit_evidence", "sub_circuit_id"
        return "allen_circuit_evidence", "allen_circuit_id"

    def _generate_evidence_id(self, cur: psycopg.Cursor, schema: str, table: str) -> str:
        for _ in range(8):
            candidate = f"EVD_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            cur.execute(f"select 1 from {schema}.{table} where evidence_id=%s", (candidate,))
            if not cur.fetchone():
                return candidate
        return _make_id("evidence")

    def _generate_evidence_code(self, cur: psycopg.Cursor, schema: str, table: str) -> str:
        for _ in range(8):
            candidate = f"EVC_{uuid.uuid4().hex[:10].upper()}"
            cur.execute(f"select 1 from {schema}.{table} where evidence_code=%s", (candidate,))
            if not cur.fetchone():
                return candidate
        return f"EVC_{int(time.time() * 1000)}"

    @staticmethod
    def _normalize_alias_value(raw_alias: Any, alias_is_array: bool) -> Any:
        if raw_alias is None:
            return [] if alias_is_array else ""
        if isinstance(raw_alias, list):
            alias_list = [str(x).strip() for x in raw_alias if str(x).strip()]
        else:
            alias_list = [x.strip() for x in str(raw_alias).split(",") if x.strip()]
        return alias_list if alias_is_array else ", ".join(alias_list)

    @staticmethod
    def _is_array_column(cur: psycopg.Cursor, schema: str, table: str, column: str) -> bool:
        cur.execute(
            """
            select data_type
            from information_schema.columns
            where table_schema=%s and table_name=%s and column_name=%s
            """,
            (schema, table, column),
        )
        row = cur.fetchone()
        return bool(row and str(row.get("data_type", "")).lower() == "array")

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _db_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "host": cfg.get("host", "localhost"),
            "port": int(cfg.get("port", 5432)),
            "dbname": cfg.get("dbname"),
            "user": cfg.get("user", "postgres"),
            "password": cfg.get("password", ""),
        }

    @staticmethod
    def _json(payload: Any) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False)

    # Final DB insert helpers
    def _commit_one(self, cur: psycopg.Cursor, schema: str, file_payload: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        granularity = (candidate.get("granularity_candidate") or "").strip().lower()
        if granularity not in GRANULARITY_ALLOWED:
            raise ValueError(f"invalid_granularity:{granularity or 'empty'}")

        laterality = (candidate.get("laterality_candidate") or "").strip().lower()
        if laterality not in LATERALITY_ALLOWED:
            raise ValueError(f"invalid_laterality:{laterality or 'empty'}")

        table, id_col, parent_col = self._table_route(granularity)
        parent_val = (candidate.get("parent_region_candidate") or "").strip()
        if parent_col and not parent_val:
            raise ValueError(f"missing_parent_for_{granularity}")
        if not parent_col and parent_val:
            raise ValueError("major_region_parent_must_be_empty")
        if granularity == "sub":
            cur.execute(f"select 1 from {schema}.major_brain_region where major_region_id=%s", (parent_val,))
            if not cur.fetchone():
                raise ValueError(f"parent_major_region_not_found:{parent_val}")
        if granularity == "allen":
            cur.execute(f"select 1 from {schema}.sub_brain_region where sub_region_id=%s", (parent_val,))
            if not cur.fetchone():
                raise ValueError(f"parent_sub_region_not_found:{parent_val}")
        if not parent_col:
            parent_val = ""

        region_id = self._identity.generate_region_id(cur, schema, table, id_col, granularity, candidate)
        region_code = self._identity.generate_region_code(cur, schema, table, candidate)
        payload = self._build_insert_payload(file_payload, candidate, region_id, region_code, laterality, parent_col, parent_val)

        cols = self._columns(cur, schema, table)
        missing = [k for k in payload.keys() if k not in cols]
        if missing:
            raise ValueError(f"target_table_missing_columns:{','.join(missing)}")

        col_sql = ", ".join(payload.keys())
        val_sql = ", ".join([f"%({k})s" for k in payload.keys()])
        cur.execute(f"insert into {schema}.{table} ({col_sql}) values ({val_sql}) returning {id_col}, region_code", payload)
        row = cur.fetchone()
        return {
            "target_table": f"{schema}.{table}",
            "primary_key": row[id_col],
            "region_code": row["region_code"],
            "region_id_column": id_col,
            "table": table,
            "granularity": granularity,
        }

    @staticmethod
    def _table_route(granularity: str) -> Tuple[str, str, str]:
        if granularity == "major":
            return "major_brain_region", "major_region_id", ""
        if granularity == "sub":
            return "sub_brain_region", "sub_region_id", "parent_major_region_id"
        return "allen_brain_region", "allen_region_id", "parent_sub_region_id"

    @staticmethod
    def _columns(cur: psycopg.Cursor, schema: str, table: str) -> set[str]:
        cur.execute("select column_name from information_schema.columns where table_schema=%s and table_name=%s", (schema, table))
        return {r["column_name"] for r in cur.fetchall()}

    @staticmethod
    def _build_insert_payload(
        file_payload: Dict[str, Any],
        candidate: Dict[str, Any],
        region_id: str,
        region_code: str,
        laterality: str,
        parent_col: str,
        parent_val: str,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        aliases = [x.strip() for x in (candidate.get("alias_candidates") or []) if str(x).strip()]
        payload = {
            "region_code": region_code,
            "en_name": (candidate.get("en_name_candidate") or "").strip(),
            "cn_name": (candidate.get("cn_name_candidate") or "").strip(),
            # target tables use text[] for alias; keep a real Python list for psycopg adaptation
            "alias": aliases,
            "description": (candidate.get("source_text") or "").strip(),
            "laterality": laterality,
            "region_category": (candidate.get("region_category_candidate") or "brain_region").strip(),
            "ontology_source": (candidate.get("ontology_source_candidate") or "workbench").strip(),
            "data_source": file_payload.get("filename", ""),
            "status": "active",
            "remark": f"candidate_id={candidate.get('id')};confidence={candidate.get('confidence')};method={candidate.get('extraction_method')}",
            "organism_id": "ORG_HUMAN",
            "division_id": "DIV_NON_LOBE_DIVISION_BRAIN",
            "created_at": now,
            "updated_at": now,
        }
        if region_id.startswith("REG_MAJ_"):
            payload["major_region_id"] = region_id
        elif region_id.startswith("REG_SUB_"):
            payload["sub_region_id"] = region_id
        else:
            payload["allen_region_id"] = region_id
        if parent_col:
            payload[parent_col] = parent_val
        return payload

    # ----- Final catalog (read promoted rows from production neurokg.*) -----
    def list_final_brain_regions(
        self,
        production_cfg: Dict[str, Any],
        *,
        limit: int = 200,
        data_source_substring: str = "",
    ) -> Dict[str, Any]:
        return self._list_final_tri_table(
            production_cfg,
            [
                ("major", "major_brain_region", "major_region_id"),
                ("sub", "sub_brain_region", "sub_region_id"),
                ("allen", "allen_brain_region", "allen_region_id"),
            ],
            limit=limit,
            data_source_substring=data_source_substring,
        )

    def list_final_circuits(
        self,
        production_cfg: Dict[str, Any],
        *,
        limit: int = 200,
        data_source_substring: str = "",
    ) -> Dict[str, Any]:
        return self._list_final_tri_table(
            production_cfg,
            [
                ("major", "major_circuit", "major_circuit_id"),
                ("sub", "sub_circuit", "sub_circuit_id"),
                ("allen", "allen_circuit", "allen_circuit_id"),
            ],
            limit=limit,
            data_source_substring=data_source_substring,
        )

    def list_final_connections(
        self,
        production_cfg: Dict[str, Any],
        *,
        limit: int = 200,
        data_source_substring: str = "",
    ) -> Dict[str, Any]:
        return self._list_final_tri_table(
            production_cfg,
            [
                ("major", "major_connection", "major_connection_id"),
                ("sub", "sub_connection", "sub_connection_id"),
                ("allen", "allen_connection", "allen_connection_id"),
            ],
            limit=limit,
            data_source_substring=data_source_substring,
        )

    def _list_final_tri_table(
        self,
        production_cfg: Dict[str, Any],
        specs: List[Tuple[str, str, str]],
        *,
        limit: int,
        data_source_substring: str,
    ) -> Dict[str, Any]:
        if not (production_cfg or {}).get("dbname"):
            return {"ok": False, "error": "production_db_not_configured", "items": [], "warnings": []}
        schema = (production_cfg or {}).get("schema", "neurokg")
        where_clause = ""
        params: List[Any] = []
        if (data_source_substring or "").strip():
            where_clause = " where coalesce(data_source,'') ilike %s"
            params.append(f"%{data_source_substring.strip()}%")
        items: List[Dict[str, Any]] = []
        warnings: List[str] = []
        cap = max(1, min(int(limit or 200), 2000))
        try:
            with psycopg.connect(**self._db_cfg(production_cfg), row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    for gran, table, id_col in specs:
                        try:
                            q = (
                                f"select * from {schema}.{table} {where_clause} "
                                f"order by coalesce(updated_at, created_at) desc nulls last limit %s"
                            )
                            cur.execute(q, tuple(params + [cap]))
                            for row in cur.fetchall():
                                d = dict(row)
                                d["_final_granularity"] = gran
                                d["_final_table"] = table
                                d["_id_column"] = id_col
                                items.append(d)
                        except Exception as exc:
                            warnings.append(f"{schema}.{table}:{exc}")
        except Exception as exc:
            return {"ok": False, "error": str(exc), "items": [], "warnings": warnings}
        items.sort(
            key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""),
            reverse=True,
        )
        return {"ok": True, "error": "", "items": items[:cap], "warnings": warnings}
