from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict

import psycopg


class RegionIdentityService:
    """Generate stable-enough region ids/codes with collision checks."""

    _PREFIX = {
        "major": "REG_MAJ_",
        "sub": "REG_SUB_",
        "allen": "REG_ALL_",
    }

    def generate_region_id(
        self,
        cur: psycopg.Cursor,
        schema: str,
        table: str,
        id_col: str,
        granularity: str,
        candidate: Dict[str, object],
    ) -> str:
        prefix = self._PREFIX[granularity]
        seed = f"{candidate.get('en_name_candidate', '')}|{candidate.get('cn_name_candidate', '')}|{datetime.now(timezone.utc).timestamp()}"
        code = f"{prefix}{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10].upper()}"
        while True:
            cur.execute(f"select 1 from {schema}.{table} where {id_col}=%s", (code,))
            if not cur.fetchone():
                return code
            code = f"{prefix}{hashlib.sha1((code + 'x').encode('utf-8')).hexdigest()[:10].upper()}"

    def generate_region_code(
        self,
        cur: psycopg.Cursor,
        schema: str,
        table: str,
        candidate: Dict[str, object],
    ) -> str:
        base = ((candidate.get("en_name_candidate") or candidate.get("cn_name_candidate") or "REGION").upper().replace(" ", "_"))
        base = "".join(ch for ch in base if ch.isalnum() or ch == "_")[:24] or "REGION"
        suffix = hashlib.sha1(
            f"{candidate.get('file_id', '')}{candidate.get('id', '')}{datetime.now(timezone.utc).timestamp()}".encode("utf-8")
        ).hexdigest()[:8].upper()
        code = f"{base}_{suffix}"
        while True:
            cur.execute(f"select 1 from {schema}.{table} where region_code=%s", (code,))
            if not cur.fetchone():
                return code
            code = f"{base}_{hashlib.sha1((code + 'x').encode('utf-8')).hexdigest()[:8].upper()}"
