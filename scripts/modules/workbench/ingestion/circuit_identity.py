from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict

import psycopg


class CircuitIdentityService:
    _PREFIX = {
        "major": "CIR_MAJ_",
        "sub": "CIR_SUB_",
        "allen": "CIR_ALL_",
    }

    def generate_circuit_id(
        self,
        cur: psycopg.Cursor,
        schema: str,
        table: str,
        id_col: str,
        granularity: str,
        circuit: Dict[str, object],
    ) -> str:
        prefix = self._PREFIX[granularity]
        seed = f"{circuit.get('en_name') or circuit.get('cn_name') or 'CIRCUIT'}|{datetime.now(timezone.utc).timestamp()}"
        code = f"{prefix}{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10].upper()}"
        while True:
            cur.execute(f"select 1 from {schema}.{table} where {id_col}=%s", (code,))
            if not cur.fetchone():
                return code
            code = f"{prefix}{hashlib.sha1((code + 'x').encode('utf-8')).hexdigest()[:10].upper()}"

    def generate_circuit_code(
        self,
        cur: psycopg.Cursor,
        schema: str,
        table: str,
        circuit: Dict[str, object],
    ) -> str:
        base = ((circuit.get("en_name") or circuit.get("cn_name") or "CIRCUIT").upper().replace(" ", "_"))
        base = "".join(ch for ch in base if ch.isalnum() or ch == "_")[:24] or "CIRCUIT"
        suffix = hashlib.sha1(
            f"{circuit.get('source_candidate_circuit_id','')}{datetime.now(timezone.utc).timestamp()}".encode("utf-8")
        ).hexdigest()[:8].upper()
        code = f"{base}_{suffix}"
        while True:
            cur.execute(f"select 1 from {schema}.{table} where circuit_code=%s", (code,))
            if not cur.fetchone():
                return code
            code = f"{base}_{hashlib.sha1((code + 'x').encode('utf-8')).hexdigest()[:8].upper()}"
