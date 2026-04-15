"""四层管线编排（v2）：标准化 → 召回 → 本地判定/后处理 → 带 evidence 的 CandidateRegion。"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from ..common.id_utils import make_id
from ..common.models import CandidateRegion, utc_now_iso
from .region_postprocess_v2 import dedupe_candidates, to_candidate_region_payload
from .region_recall_v2 import recall_from_cell
from .region_registry_config import column_role_for_header, load_registry_overlay


def _log(emit: Optional[Callable[..., None]], msg: str, detail: Optional[Dict[str, Any]] = None) -> None:
    if emit:
        try:
            emit(msg, detail or {})
        except Exception:
            pass


def _group_table_rows(table_rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_sheet: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tr in table_rows:
        by_sheet[str(tr.get("sheet") or "Sheet1")].append(tr)
    for sh in by_sheet:
        by_sheet[sh].sort(key=lambda x: int(x.get("row") or 0))
    return dict(by_sheet)


def run_region_extraction_v2(
    file_payload: Dict[str, Any],
    parsed_payload: Dict[str, Any],
    mode: str,
    deepseek_cfg: Dict[str, Any],
    *,
    root_dir: str,
    pipeline_config: Dict[str, Any],
    log_emit: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    v2 管线入口（仅本地召回 + 后处理）。由 ExtractionService 在 mode=local 且 region_extraction_v2.enabled 时调用。
    选择 DeepSeek 模式时不会进入本模块，而会走 API 分批抽取，避免「method 显示 deepseek 却未调 API」。
    DeepSeek 受约束精排（仅疑难样本）由 pipeline.region_extraction_v2.deepseek_refine 控制，见后续 Phase4。
    """
    cfg = pipeline_config.get("region_extraction_v2") or {}
    if not cfg.get("enabled", False):
        raise RuntimeError("region_extraction_v2_disabled")

    overlay = load_registry_overlay(root_dir)
    _log(log_emit, "[REGION_V2] start", {"registry_version": overlay.get("version"), "mode": mode})

    parsed_doc = parsed_payload.get("document") or {}
    table_rows: List[Dict[str, Any]] = list(parsed_doc.get("table_rows") or [])
    parsed_document_id = str(parsed_doc.get("parsed_document_id") or "")
    file_id = file_payload.get("file_id", "")

    raw_candidates: List[Dict[str, Any]] = []

    if table_rows:
        grouped = _group_table_rows(table_rows)
        for sheet_name, rows in grouped.items():
            if not rows:
                continue
            header_tr = rows[0]
            header_vals: List[str] = list(header_tr.get("values") or [])
            col_roles: List[str] = [column_role_for_header(h, overlay) for h in header_vals]
            # 与旧逻辑兼容：首行既可能为表头也可能为数据；若第二行更像数据则仍用首行作表头
            data_rows = rows[1:]
            for tr in data_rows:
                vals: List[str] = [str(x) for x in (tr.get("values") or [])]
                ridx = int(tr.get("row") or 0)
                for cidx, cell in enumerate(vals):
                    raw_cell = cell.strip() if cell else ""
                    if not raw_cell:
                        continue
                    role = col_roles[cidx] if cidx < len(col_roles) else "unknown"
                    raw_candidates.extend(
                        recall_from_cell(
                            raw_cell,
                            overlay=overlay,
                            sheet=sheet_name,
                            row_idx=ridx,
                            col_idx=cidx + 1,
                            column_role=role,
                        )
                    )
        _log(
            log_emit,
            "[REGION_V2] recall_done",
            {"raw_candidates": len(raw_candidates), "sheets": list(grouped.keys())},
        )
    else:
        # 无非结构化表：按 chunk 行做弱召回
        chunks = parsed_payload.get("chunks") or []
        for i, ch in enumerate(chunks[:2000]):
            txt = (ch.get("text_content") or "").strip()
            if not txt or len(txt) > 500:
                continue
            raw_candidates.extend(
                recall_from_cell(
                    txt,
                    overlay=overlay,
                    sheet="",
                    row_idx=i + 1,
                    col_idx=1,
                    column_role="brain_region_primary",
                )
            )
        _log(log_emit, "[REGION_V2] recall_from_chunks", {"raw_candidates": len(raw_candidates)})

    merged = dedupe_candidates(raw_candidates)
    _log(log_emit, "[REGION_V2] postprocess_done", {"merged": len(merged)})

    # 可选：DeepSeek 仅对 review_needed / unresolved 精排（Phase4）
    if cfg.get("deepseek_refine") and mode == "deepseek" and deepseek_cfg.get("enabled"):
        _log(log_emit, "[REGION_V2] deepseek_refine_skipped_stub", {"reason": "enable_in_phase4"})

    out_rows: List[CandidateRegion] = []
    for c in merged:
        if c.get("match_type") == "rejected_blacklist" and cfg.get("drop_rejected", False):
            continue
        drow, _note = to_candidate_region_payload(
            c,
            file_id=file_id,
            parsed_document_id=parsed_document_id,
            extraction_method=f"region_v2_{mode}",
        )
        drow["id"] = make_id("cr")
        drow["created_at"] = utc_now_iso()
        drow["updated_at"] = utc_now_iso()
        out_rows.append(
            CandidateRegion(
                id=drow["id"],
                file_id=drow["file_id"],
                parsed_document_id=drow["parsed_document_id"],
                chunk_id=drow["chunk_id"],
                source_text=drow["source_text"],
                en_name_candidate=drow["en_name_candidate"],
                cn_name_candidate=drow["cn_name_candidate"],
                alias_candidates=drow["alias_candidates"],
                laterality_candidate=drow["laterality_candidate"],
                region_category_candidate=drow["region_category_candidate"],
                granularity_candidate=drow["granularity_candidate"],
                parent_region_candidate=drow["parent_region_candidate"],
                ontology_source_candidate=drow["ontology_source_candidate"],
                confidence=drow["confidence"],
                extraction_method=drow["extraction_method"],
                llm_model=drow["llm_model"],
                status=drow["status"],
                review_note=drow["review_note"],
                created_at=drow["created_at"],
                updated_at=drow["updated_at"],
            )
        )

    if not out_rows:
        note = json.dumps(
            {"wb_v2": {"extract_status": "unresolved", "reason": "no_candidates_after_recall"}},
            ensure_ascii=False,
        )
        out_rows.append(
            CandidateRegion(
                id=make_id("cr"),
                file_id=file_id,
                parsed_document_id=parsed_document_id,
                chunk_id="",
                source_text=file_payload.get("filename", ""),
                en_name_candidate="",
                cn_name_candidate="",
                alias_candidates=[],
                laterality_candidate="unknown",
                region_category_candidate="brain_region",
                granularity_candidate="unknown",
                parent_region_candidate="",
                ontology_source_candidate="region_pipeline_v2",
                confidence=0.2,
                extraction_method=f"region_v2_{mode}",
                llm_model="",
                status="pending_review",
                review_note=note,
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
            )
        )

    _log(log_emit, "[REGION_V2] complete", {"candidates": len(out_rows)})
    return {"method": f"region_v2_{mode}", "llm_model": deepseek_cfg.get("model", "") if mode == "deepseek" else "", "candidates": out_rows}
