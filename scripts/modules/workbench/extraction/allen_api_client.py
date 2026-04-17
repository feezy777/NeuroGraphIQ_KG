"""Allen Brain Atlas RESTful Model Access (RMA) — Structure 查询。

基址：http://api.brain-map.org/api/v2/data/query.json
默认使用成年小鼠结构图 graph_id=1（Allen 常用参考）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ALLEN_DATA_QUERY_URL = "http://api.brain-map.org/api/v2/data/query.json"
DEFAULT_TIMEOUT = 45.0
MOUSE_STRUCTURE_GRAPH_ID = 1


def _build_query(criteria: str, *, num_rows: int, start_row: int = 0) -> str:
    opts = f"num_rows$eq{num_rows}"
    if start_row:
        opts += f",start_row$eq{start_row}"
    return f"model::Structure,rma::criteria,{criteria},rma::options[{opts}]"


def query_structures_json(
    criteria: str,
    *,
    num_rows: int = 50,
    start_row: int = 0,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    q = _build_query(criteria, num_rows=num_rows, start_row=start_row)
    url = ALLEN_DATA_QUERY_URL + "?q=" + quote(q, safe="")
    req = Request(url, headers={"User-Agent": "NeuroGraphIQ-Workbench/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"allen_http_{exc.code}:{exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"allen_transport_failed:{exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("allen_invalid_json") from exc


def fetch_structures_by_ids(
    ids: List[int],
    *,
    graph_id: int = MOUSE_STRUCTURE_GRAPH_ID,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[int, Dict[str, Any]]:
    """批量按 id 拉取 Structure，用于解析 parent_structure_id 名称。"""
    out: Dict[int, Dict[str, Any]] = {}
    if not ids:
        return out
    chunk_size = 80
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        id_list = ",".join(str(x) for x in chunk)
        crit = f"[graph_id$eq{graph_id}][id$in{id_list}]"
        data = query_structures_json(crit, num_rows=len(chunk) + 5, timeout=timeout)
        if not data.get("success"):
            raise RuntimeError(f"allen_api_query_failed:{data}")
        for row in data.get("msg") or []:
            if isinstance(row, dict) and "id" in row:
                try:
                    out[int(row["id"])] = row
                except (TypeError, ValueError):
                    continue
    return out


def fetch_structures_mouse(
    *,
    graph_id: int = MOUSE_STRUCTURE_GRAPH_ID,
    acronym_exact: Optional[str] = None,
    acronym_pattern: Optional[str] = None,
    structure_id: Optional[int] = None,
    max_rows: int = 50,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """
    拉取小鼠 Structure 列表。三者互斥优先级：structure_id > acronym_exact > acronym_pattern。

    acronym_pattern 使用 RMA 的 $li 运算符；若未含 *，则自动包成 *关键词*。
    """
    max_rows = max(1, min(int(max_rows), 200))
    if structure_id is not None:
        crit = f"[graph_id$eq{graph_id}][id$eq{int(structure_id)}]"
    elif acronym_exact:
        ac = acronym_exact.strip()
        if not ac:
            raise ValueError("allen_acronym_exact_empty")
        crit = f"[graph_id$eq{graph_id}][acronym$eq{ac}]"
    elif acronym_pattern:
        pat = acronym_pattern.strip()
        if not pat:
            raise ValueError("allen_acronym_pattern_empty")
        if "*" not in pat:
            pat = f"*{pat}*"
        crit = f"[graph_id$eq{graph_id}][acronym$li{pat}]"
    else:
        raise ValueError("allen_need_structure_id_or_acronym")

    data = query_structures_json(crit, num_rows=max_rows, timeout=timeout)
    if not data.get("success"):
        raise RuntimeError(f"allen_api_query_failed:{data}")
    rows = data.get("msg") or []
    return [r for r in rows if isinstance(r, dict)]


def resolve_parent_names(
    structures: List[Dict[str, Any]],
    *,
    graph_id: int = MOUSE_STRUCTURE_GRAPH_ID,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[int, str]:
    parent_ids: List[int] = []
    for r in structures:
        pid = r.get("parent_structure_id")
        if pid is None:
            continue
        try:
            parent_ids.append(int(pid))
        except (TypeError, ValueError):
            continue
    parent_ids = sorted(set(parent_ids))
    id_to_row = fetch_structures_by_ids(parent_ids, graph_id=graph_id, timeout=timeout)
    return {pid: (id_to_row[pid].get("name") or "").strip() for pid in parent_ids if pid in id_to_row}
