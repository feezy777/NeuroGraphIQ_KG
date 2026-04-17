from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

import psycopg
from psycopg.rows import dict_row

from ..config.runtime_config import db_config, load_runtime
from .id_utils import derive_global_region_id_for_row
from .models import utc_now_iso


class StateStore:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = Path(root_dir)
        self._lock = Lock()
        self._state_path = self.root_dir / "artifacts" / "workbench" / "state.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._internal_events: List[Dict[str, Any]] = []

        self._runtime = load_runtime(str(self.root_dir))
        self._cfg = db_config(self._runtime, "workbench_db")
        self._schema = self._cfg.get("schema", "workbench")
        self._pg_enabled = False

        if str(self._runtime.get("database", {}).get("backend", "json")).lower() == "postgres":
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("select 1")
                self._pg_enabled = True
                self._event("repository_switched_to_pg", "workbench repository uses PostgreSQL")
                self._ensure_schema_compat()
                self._migrate_json_if_needed()
            except Exception as exc:
                self._event("pg_init_failed", f"postgres unavailable: {exc}", level="warning")

        if not self._state_path.exists():
            self._save_json(self._default_state())

    def consume_internal_events(self) -> List[Dict[str, Any]]:
        rows = list(self._internal_events)
        self._internal_events.clear()
        return rows

    def _event(self, event_type: str, message: str, level: str = "info", detail_json: Dict[str, Any] | None = None) -> None:
        event = {
            "event_type": event_type,
            "message": message,
            "level": level,
            "detail_json": detail_json or {},
            "created_at": utc_now_iso(),
        }
        self._internal_events.append(event)
        print(f"[REPOSITORY] {event_type} {message}", flush=True)
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"insert into {self._schema}.task_log_v2 (id, run_id, level, event_type, message, detail_json, created_at) values (%s,%s,%s,%s,%s,%s::jsonb,%s)",
                            (
                                f"log_repo_{event_type}_{len(self._internal_events)}_{event['created_at'].replace(':', '').replace('-', '').replace('T', '').replace('Z', '')}",
                                "-",
                                level,
                                event_type,
                                message,
                                self._to_json({"module": "REPOSITORY", **(detail_json or {})}, {}),
                                event["created_at"],
                            ),
                        )
                    conn.commit()
            except Exception:
                pass
        try:
            state = self._load_json()
            logs = state.setdefault("task_logs", [])
            logs.append(
                {
                    "log_id": f"log_repo_{len(logs) + 1}",
                    "run_id": "-",
                    "level": level,
                    "event_type": event_type,
                    "module": "REPOSITORY",
                    "message": message,
                    "detail_json": detail_json or {},
                    "created_at": event["created_at"],
                }
            )
            state["task_logs"] = logs[-5000:]
            self._save_json(state)
        except Exception:
            pass

    def _default_state(self) -> Dict[str, Any]:
        return {
            "files": {},
            "parsed_documents": {},
            "candidate_regions": [],
            "candidate_circuits": [],
            "candidate_connections": [],
            "review_records": [],
            "tasks": {},
            "task_logs": [],
            "workspace_snapshot": {},
            "region_result_versions": [],
        }

    def _load_json(self) -> Dict[str, Any]:
        with self._lock:
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            base = self._default_state()
            base.update(data)
            return base

    def _save_json(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return dict(obj)
        if is_dataclass(obj):
            return asdict(obj)
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)
        return {}

    def _to_json(self, value: Any, default: Any) -> str:
        return json.dumps(value if value is not None else default, ensure_ascii=False)

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                row = json.loads(value)
                return row if isinstance(row, dict) else {}
            except Exception:
                return {}
        return {}

    def _as_list(self, value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                row = json.loads(value)
                return row if isinstance(row, list) else []
            except Exception:
                return []
        return []

    def _ts(self, value: Any) -> str:
        return str(value).replace("+00:00", "Z") if value else ""

    def _conn(self):
        return psycopg.connect(
            host=self._cfg.get("host", "localhost"),
            port=int(self._cfg.get("port", 5432)),
            dbname=self._cfg.get("dbname"),
            user=self._cfg.get("user", "postgres"),
            password=self._cfg.get("password", ""),
            row_factory=dict_row,
        )

    def _ensure_schema_compat(self) -> None:
        stmts = [
            f"create schema if not exists {self._schema}",
            f"create table if not exists {self._schema}.uploaded_file (id text primary key, file_name text not null default '', file_type text not null default 'unknown', mime_type text not null default '', storage_path text not null default '', content_ref text not null default '', size_bytes bigint not null default 0, upload_status text not null default 'uploaded', source text not null default 'upload', metadata_json jsonb not null default '{{}}'::jsonb, tags_json jsonb not null default '[]'::jsonb, latest_parse_task_id text not null default '', latest_extract_task_id text not null default '', latest_validate_task_id text not null default '', latest_map_task_id text not null default '', latest_ingest_task_id text not null default '', latest_commit_task_id text not null default '', version integer not null default 1, checksum text not null default '', path text not null default '', created_at timestamptz not null default now(), updated_at timestamptz not null default now(), deleted_at timestamptz)",
            f"create table if not exists {self._schema}.parsed_document (id bigserial primary key, file_id text not null, title text, file_type text, source text, authors_json jsonb not null default '[]'::jsonb, year integer, doi text, page_range text, parser_name text, parser_version text, document_json jsonb not null default '{{}}'::jsonb, created_at timestamptz not null default now(), unique(file_id))",
            f"create table if not exists {self._schema}.content_chunk (id bigserial primary key, chunk_id text not null unique, file_id text not null, chunk_type text not null default 'paragraph', chunk_text text, source_location_json jsonb not null default '{{}}'::jsonb, metadata_json jsonb not null default '{{}}'::jsonb, created_at timestamptz not null default now())",
            f"create table if not exists {self._schema}.candidate_region (id text primary key, file_id text not null, parsed_document_id text not null default '', chunk_id text not null default '', source_text text not null default '', en_name_candidate text not null default '', cn_name_candidate text not null default '', alias_candidates jsonb not null default '[]'::jsonb, laterality_candidate text not null default 'unknown', region_category_candidate text not null default 'brain_region', granularity_candidate text not null default 'unknown', parent_region_candidate text not null default '', ontology_source_candidate text not null default 'workbench', confidence numeric(7,4) not null default 0, extraction_method text not null default 'local_rule', llm_model text not null default '', status text not null default 'pending_review', review_note text not null default '', created_at timestamptz not null default now(), updated_at timestamptz not null default now())",
            f"create table if not exists {self._schema}.candidate_circuit_node (id text primary key, candidate_circuit_id text not null, file_id text not null default '', region_id_candidate text not null default '', granularity_candidate text not null default 'unknown', node_order integer not null default 1, role_label text not null default '', created_at timestamptz not null default now())",
            f"create table if not exists {self._schema}.candidate_connection (id bigserial primary key, connection_id text not null unique, file_id text not null default '', source_region text not null default '', target_region text not null default '', directionality text not null default 'unknown', confidence numeric(7,4) not null default 0, evidence_chunk_ids jsonb not null default '[]'::jsonb, created_at timestamptz not null default now())",
            f"create table if not exists {self._schema}.task_run (task_id text primary key, task_type text not null default '', status text not null default 'queued', actor text not null default '', input_object_json jsonb not null default '{{}}'::jsonb, model_or_rule_version text not null default '', parameters_json jsonb not null default '{{}}'::jsonb, output_summary_json jsonb not null default '{{}}'::jsonb, error_reason text not null default '', started_at timestamptz, ended_at timestamptz, created_at timestamptz not null default now())",
            f"create table if not exists {self._schema}.extraction_run (id text primary key, file_id text not null default '', task_type text not null default '', trigger_source text not null default 'ui', model_name text not null default '', params_json jsonb not null default '{{}}'::jsonb, status text not null default 'queued', started_at timestamptz, finished_at timestamptz, summary text not null default '', error_message text not null default '')",
            f"create table if not exists {self._schema}.task_log_v2 (id text primary key, run_id text not null default '-', level text not null default 'info', event_type text not null default 'log_event', message text not null default '', detail_json jsonb not null default '{{}}'::jsonb, created_at timestamptz not null default now())",
            f"create table if not exists {self._schema}.review_record (id text primary key, candidate_region_id text not null, reviewer text not null default '', action text not null, before_json jsonb not null default '{{}}'::jsonb, after_json jsonb not null default '{{}}'::jsonb, note text not null default '', created_at timestamptz not null)",
            f"alter table {self._schema}.candidate_region add column if not exists region_category_candidate text not null default 'brain_region'",
            f"alter table {self._schema}.candidate_region add column if not exists ontology_source_candidate text not null default 'workbench'",
            f"alter table {self._schema}.candidate_circuit add column if not exists file_id text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists parsed_document_id text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists source_text text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists en_name_candidate text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists cn_name_candidate text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists alias_candidates jsonb not null default '[]'::jsonb",
            f"alter table {self._schema}.candidate_circuit add column if not exists description_candidate text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists circuit_kind_candidate text not null default 'unknown'",
            f"alter table {self._schema}.candidate_circuit add column if not exists loop_type_candidate text not null default 'inferred'",
            f"alter table {self._schema}.candidate_circuit add column if not exists cycle_verified_candidate boolean not null default false",
            f"alter table {self._schema}.candidate_circuit add column if not exists confidence_circuit numeric(7,4) not null default 0",
            f"alter table {self._schema}.candidate_circuit add column if not exists granularity_candidate text not null default 'unknown'",
            f"alter table {self._schema}.candidate_circuit add column if not exists extraction_method text not null default 'local_rule'",
            f"alter table {self._schema}.candidate_circuit add column if not exists llm_model text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists status text not null default 'pending_review'",
            f"alter table {self._schema}.candidate_circuit add column if not exists review_note text not null default ''",
            f"alter table {self._schema}.candidate_circuit add column if not exists created_at timestamptz not null default now()",
            f"alter table {self._schema}.candidate_circuit add column if not exists updated_at timestamptz not null default now()",
            f"alter table {self._schema}.candidate_connection add column if not exists parsed_document_id text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists source_text text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists en_name_candidate text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists cn_name_candidate text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists alias_candidates jsonb not null default '[]'::jsonb",
            f"alter table {self._schema}.candidate_connection add column if not exists description_candidate text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists granularity_candidate text not null default 'unknown'",
            f"alter table {self._schema}.candidate_connection add column if not exists connection_modality_candidate text not null default 'unknown'",
            f"alter table {self._schema}.candidate_connection add column if not exists source_region_ref_candidate text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists target_region_ref_candidate text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists direction_label text not null default 'unknown'",
            f"alter table {self._schema}.candidate_connection add column if not exists extraction_method text not null default 'local_rule'",
            f"alter table {self._schema}.candidate_connection add column if not exists llm_model text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists status text not null default 'pending_review'",
            f"alter table {self._schema}.candidate_connection add column if not exists review_note text not null default ''",
            f"alter table {self._schema}.candidate_connection add column if not exists updated_at timestamptz not null default now()",
            f"alter table {self._schema}.uploaded_file add column if not exists metadata_json jsonb not null default '{{}}'::jsonb",
            f"alter table {self._schema}.uploaded_file add column if not exists tags_json jsonb not null default '[]'::jsonb",
            f"alter table {self._schema}.uploaded_file add column if not exists latest_parse_task_id text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists latest_extract_task_id text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists latest_validate_task_id text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists latest_map_task_id text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists latest_ingest_task_id text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists latest_commit_task_id text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists version integer not null default 1",
            f"alter table {self._schema}.uploaded_file add column if not exists checksum text not null default ''",
            f"alter table {self._schema}.uploaded_file add column if not exists path text not null default ''",
            f"create index if not exists idx_candidate_circuit_file on {self._schema}.candidate_circuit(file_id, status)",
            f"create index if not exists idx_candidate_circuit_node_circuit on {self._schema}.candidate_circuit_node(candidate_circuit_id, node_order)",
            f"create index if not exists idx_candidate_connection_file on {self._schema}.candidate_connection(file_id, status)",
            f"create table if not exists {self._schema}.workspace_snapshot (snapshot_id text primary key, payload_json jsonb not null default '{{}}'::jsonb, updated_at timestamptz not null default now())",
            f"alter table {self._schema}.candidate_region add column if not exists lane text not null default 'local'",
            f"alter table {self._schema}.candidate_circuit add column if not exists lane text not null default 'local'",
            f"alter table {self._schema}.candidate_connection add column if not exists lane text not null default 'local'",
            f"create index if not exists idx_candidate_region_file_lane on {self._schema}.candidate_region(file_id, lane)",
            f"create index if not exists idx_candidate_circuit_file_lane on {self._schema}.candidate_circuit(file_id, lane)",
            f"create index if not exists idx_candidate_connection_file_lane on {self._schema}.candidate_connection(file_id, lane)",
        ]
        with self._conn() as conn:
            with conn.cursor() as cur:
                for stmt in stmts:
                    cur.execute(stmt)
            conn.commit()

    def _migrate_json_if_needed(self) -> None:
        if not self._state_path.exists():
            return
        state = self._load_json()
        if not state.get("files"):
            return
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"select count(1) as c from {self._schema}.uploaded_file where deleted_at is null")
                    if int(cur.fetchone().get("c", 0)) > 0:
                        return
        except Exception:
            return

        self._event("migration_started", "json->postgres migration started")
        try:
            for row in state.get("files", {}).values():
                if isinstance(row, dict):
                    self._put_file_pg(row)
            for row in state.get("tasks", {}).values():
                if isinstance(row, dict):
                    self._put_task_pg(row)
            for row in state.get("task_logs", []):
                if isinstance(row, dict):
                    self._append_task_log_pg(row)
            for file_id, parsed in state.get("parsed_documents", {}).items():
                if not isinstance(parsed, dict):
                    continue
                doc = parsed.get("document", {})
                chunks = parsed.get("chunks", [])
                if file_id and doc:
                    self._put_parsed_pg(doc, chunks)
            by_file: Dict[str, List[Dict[str, Any]]] = {}
            for row in state.get("candidate_regions", []):
                if isinstance(row, dict):
                    by_file.setdefault(row.get("file_id", ""), []).append(row)
            for file_id, rows in by_file.items():
                if file_id:
                    self._put_region_candidates_pg(file_id, rows)
            by_file_circuit: Dict[str, List[Dict[str, Any]]] = {}
            for row in state.get("candidate_circuits", []):
                if isinstance(row, dict):
                    by_file_circuit.setdefault(row.get("file_id", ""), []).append(row)
            for file_id, rows in by_file_circuit.items():
                if file_id:
                    self._put_circuit_candidates_pg(file_id, rows)
            by_file_connection: Dict[str, List[Dict[str, Any]]] = {}
            for row in state.get("candidate_connections", []):
                if isinstance(row, dict):
                    by_file_connection.setdefault(row.get("file_id", ""), []).append(row)
            for file_id, rows in by_file_connection.items():
                if file_id:
                    self._put_connection_candidates_pg(file_id, rows)
            for row in state.get("review_records", []):
                if isinstance(row, dict):
                    self._append_review_pg(row)
            if state.get("workspace_snapshot"):
                self._put_workspace_snapshot_pg(state.get("workspace_snapshot", {}))
            self._event("migration_succeeded", "json->postgres migration succeeded")
        except Exception as exc:
            self._event("migration_failed", f"json->postgres migration failed: {exc}", level="error")
    # file operations
    def put_file(self, record: Any) -> Dict[str, Any]:
        payload = self._to_dict(record)
        if self._pg_enabled:
            try:
                self._put_file_pg(payload)
                return self.get_file(payload.get("file_id", "")) or payload
            except Exception as exc:
                self._event("pg_write_failed", f"put_file fallback: {exc}", "warning")
        state = self._load_json()
        state["files"][payload["file_id"]] = payload
        self._save_json(state)
        return payload

    def list_files(self) -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"select id, file_name, file_type, mime_type, upload_status, version, source, size_bytes, checksum, path, tags_json, metadata_json, latest_parse_task_id, latest_extract_task_id, latest_validate_task_id, latest_map_task_id, latest_ingest_task_id, latest_commit_task_id, created_at, updated_at from {self._schema}.uploaded_file where deleted_at is null order by created_at desc"
                        )
                        rows = cur.fetchall()
                return [self._row_to_file(r) for r in rows]
            except Exception as exc:
                self._event("pg_read_failed", f"list_files fallback: {exc}", "warning")
        return list(self._load_json().get("files", {}).values())

    def get_file(self, file_id: str) -> Dict[str, Any] | None:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"select id, file_name, file_type, mime_type, upload_status, version, source, size_bytes, checksum, path, tags_json, metadata_json, latest_parse_task_id, latest_extract_task_id, latest_validate_task_id, latest_map_task_id, latest_ingest_task_id, latest_commit_task_id, created_at, updated_at from {self._schema}.uploaded_file where id=%s and deleted_at is null",
                            (file_id,),
                        )
                        row = cur.fetchone()
                return self._row_to_file(row) if row else None
            except Exception as exc:
                self._event("pg_read_failed", f"get_file fallback: {exc}", "warning")
        return self._load_json().get("files", {}).get(file_id)

    def update_file(self, file_id: str, **kwargs: Any) -> Dict[str, Any]:
        if self._pg_enabled:
            try:
                self._update_file_pg(file_id, kwargs)
                return self.get_file(file_id) or {}
            except Exception as exc:
                self._event("pg_write_failed", f"update_file fallback: {exc}", "warning")
        state = self._load_json()
        row = state.get("files", {}).get(file_id, {})
        row.update(kwargs)
        state["files"][file_id] = row
        self._save_json(state)
        return row

    def remove_file(self, file_id: str) -> None:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"delete from {self._schema}.uploaded_file where id=%s", (file_id,))
                        cur.execute(f"delete from {self._schema}.candidate_region where file_id=%s", (file_id,))
                        cur.execute(f"delete from {self._schema}.candidate_circuit_node where file_id=%s", (file_id,))
                        cur.execute(f"delete from {self._schema}.candidate_circuit where file_id=%s", (file_id,))
                        cur.execute(f"delete from {self._schema}.candidate_connection where file_id=%s", (file_id,))
                    conn.commit()
                return
            except Exception as exc:
                self._event("pg_write_failed", f"remove_file fallback: {exc}", "warning")
        state = self._load_json()
        state.get("files", {}).pop(file_id, None)
        state.get("parsed_documents", {}).pop(file_id, None)
        state["candidate_regions"] = [x for x in state.get("candidate_regions", []) if x.get("file_id") != file_id]
        state["candidate_circuits"] = [x for x in state.get("candidate_circuits", []) if x.get("file_id") != file_id]
        state["candidate_connections"] = [x for x in state.get("candidate_connections", []) if x.get("file_id") != file_id]
        self._save_json(state)

    def _put_file_pg(self, payload: Dict[str, Any]) -> None:
        now = payload.get("updated_at") or utc_now_iso()
        created = payload.get("created_at") or now
        metadata = payload.get("metadata", {})
        tags = payload.get("tags", [])
        params = {
            "file_id": payload.get("file_id", ""),
            "filename": payload.get("filename", ""),
            "file_type": payload.get("file_type", "unknown"),
            "mime_type": payload.get("mime_type", ""),
            "status": payload.get("status", "uploaded"),
            "version": int(payload.get("version", 1)),
            "source": payload.get("source", "upload"),
            "size_bytes": int(payload.get("size_bytes", 0)),
            "checksum": metadata.get("file_hash", payload.get("checksum", "")),
            "path": payload.get("path", ""),
            "tags_json": self._to_json(tags, []),
            "metadata_json": self._to_json(metadata, {}),
            "latest_parse_task_id": payload.get("latest_parse_task_id", ""),
            "latest_extract_task_id": payload.get("latest_extract_task_id", ""),
            "latest_validate_task_id": payload.get("latest_validate_task_id", ""),
            "latest_map_task_id": payload.get("latest_map_task_id", ""),
            "latest_ingest_task_id": payload.get("latest_ingest_task_id", ""),
            "latest_commit_task_id": payload.get("latest_commit_task_id", ""),
            "created_at": created,
            "updated_at": now,
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"select version from {self._schema}.uploaded_file where id=%s", (params["file_id"],))
                existed = cur.fetchone()
                if not existed:
                    cur.execute(
                        f"select coalesce(max(version), 0) + 1 as next_version from {self._schema}.uploaded_file where file_name=%s",
                        (params["filename"],),
                    )
                    next_version = int((cur.fetchone() or {}).get("next_version", 1))
                    params["version"] = max(int(params.get("version", 1)), next_version)
                cur.execute(
                    f"""
                    insert into {self._schema}.uploaded_file (
                      id, file_name, file_type, mime_type, storage_path, content_ref, path,
                      size_bytes, upload_status, source, metadata_json, tags_json,
                      latest_parse_task_id, latest_extract_task_id, latest_validate_task_id, latest_map_task_id, latest_ingest_task_id, latest_commit_task_id,
                      version, checksum, created_at, updated_at, deleted_at
                    ) values (
                      %(file_id)s, %(filename)s, %(file_type)s, %(mime_type)s, %(path)s, %(path)s, %(path)s,
                      %(size_bytes)s, %(status)s, %(source)s, %(metadata_json)s::jsonb, %(tags_json)s::jsonb,
                      %(latest_parse_task_id)s, %(latest_extract_task_id)s, %(latest_validate_task_id)s, %(latest_map_task_id)s, %(latest_ingest_task_id)s, %(latest_commit_task_id)s,
                      %(version)s, %(checksum)s, %(created_at)s, %(updated_at)s, null
                    )
                    on conflict (id) do update set
                      file_name=excluded.file_name,
                      file_type=excluded.file_type,
                      mime_type=excluded.mime_type,
                      storage_path=excluded.storage_path,
                      content_ref=excluded.content_ref,
                      path=excluded.path,
                      size_bytes=excluded.size_bytes,
                      upload_status=excluded.upload_status,
                      source=excluded.source,
                      metadata_json=excluded.metadata_json,
                      tags_json=excluded.tags_json,
                      latest_parse_task_id=excluded.latest_parse_task_id,
                      latest_extract_task_id=excluded.latest_extract_task_id,
                      latest_validate_task_id=excluded.latest_validate_task_id,
                      latest_map_task_id=excluded.latest_map_task_id,
                      latest_ingest_task_id=excluded.latest_ingest_task_id,
                      latest_commit_task_id=excluded.latest_commit_task_id,
                      version=excluded.version,
                      checksum=excluded.checksum,
                      updated_at=excluded.updated_at,
                      deleted_at=null
                    """,
                    params,
                )
            conn.commit()

    def _update_file_pg(self, file_id: str, patch: Dict[str, Any]) -> None:
        if "path" in patch:
            patch.setdefault("storage_path", patch.get("path"))
            patch.setdefault("content_ref", patch.get("path"))
        mapping = {
            "filename": "file_name",
            "file_type": "file_type",
            "mime_type": "mime_type",
            "status": "upload_status",
            "version": "version",
            "source": "source",
            "size_bytes": "size_bytes",
            "path": "path",
            "content_ref": "content_ref",
            "storage_path": "storage_path",
            "latest_parse_task_id": "latest_parse_task_id",
            "latest_extract_task_id": "latest_extract_task_id",
            "latest_validate_task_id": "latest_validate_task_id",
            "latest_map_task_id": "latest_map_task_id",
            "latest_ingest_task_id": "latest_ingest_task_id",
            "latest_commit_task_id": "latest_commit_task_id",
            "updated_at": "updated_at",
            "metadata": "metadata_json",
            "tags": "tags_json",
            "checksum": "checksum",
        }
        sets = []
        params: Dict[str, Any] = {"file_id": file_id}
        for k, v in patch.items():
            col = mapping.get(k)
            if not col:
                continue
            if col in {"metadata_json", "tags_json"}:
                sets.append(f"{col}=%({col})s::jsonb")
                params[col] = self._to_json(v, {} if col == "metadata_json" else [])
            else:
                sets.append(f"{col}=%({col})s")
                params[col] = v
        if not sets:
            return
        if "updated_at" not in params:
            params["updated_at"] = utc_now_iso()
            sets.append("updated_at=%(updated_at)s")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"update {self._schema}.uploaded_file set {', '.join(sets)} where id=%(file_id)s", params)
            conn.commit()

    def _row_to_file(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "file_id": row.get("id", row.get("file_id", "")),
            "filename": row.get("file_name", row.get("filename", "")),
            "file_type": row.get("file_type", "unknown"),
            "mime_type": row.get("mime_type", ""),
            "status": row.get("upload_status", row.get("status", "uploaded")),
            "version": int(row.get("version", 1)),
            "source": row.get("source", "upload"),
            "size_bytes": int(row.get("size_bytes") or 0),
            "path": row.get("path", row.get("storage_path", "")),
            "created_at": self._ts(row.get("created_at")),
            "updated_at": self._ts(row.get("updated_at")),
            "latest_parse_task_id": row.get("latest_parse_task_id", ""),
            "latest_extract_task_id": row.get("latest_extract_task_id", ""),
            "latest_validate_task_id": row.get("latest_validate_task_id", ""),
            "latest_map_task_id": row.get("latest_map_task_id", ""),
            "latest_ingest_task_id": row.get("latest_ingest_task_id", ""),
            "latest_commit_task_id": row.get("latest_commit_task_id", ""),
            "tags": self._as_list(row.get("tags_json")),
            "metadata": self._as_dict(row.get("metadata_json")),
        }
    # parsed document + chunk
    def put_parsed_document(self, document: Any, chunks: Iterable[Dict[str, Any]]) -> None:
        doc = self._to_dict(document)
        chunk_rows = [self._to_dict(c) for c in chunks]
        if self._pg_enabled:
            try:
                self._put_parsed_pg(doc, chunk_rows)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"put_parsed_document fallback: {exc}", "warning")
        state = self._load_json()
        state["parsed_documents"][doc.get("file_id", "")] = {"document": doc, "chunks": chunk_rows}
        self._save_json(state)

    def get_parsed_document(self, file_id: str) -> Dict[str, Any]:
        if self._pg_enabled:
            doc_row = None
            chunk_rows: List[Any] = []
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.parsed_document where file_id=%s", (file_id,))
                        doc_row = cur.fetchone()
                        cur.execute(
                            f"select chunk_id, file_id, chunk_type, chunk_text, source_location_json, metadata_json from {self._schema}.content_chunk where file_id=%s order by id asc",
                            (file_id,),
                        )
                        chunk_rows = cur.fetchall()
            except Exception as exc:
                # Real DB connectivity / query error – fall back to JSON and log as warning.
                self._event("pg_read_failed", f"get_parsed_document pg_error: {exc}", "warning")
                return self._load_json().get("parsed_documents", {}).get(file_id, {"document": {}, "chunks": []})

            if not doc_row:
                # PG has no row for this file_id yet. This is expected when:
                #   (a) _put_parsed_pg failed and wrote to JSON instead, or
                #   (b) the file was parsed before PG was enabled.
                # Fall through silently to JSON store – this is NOT a database error.
                json_result = self._load_json().get("parsed_documents", {}).get(file_id)
                if json_result:
                    return json_result
                return {"document": {}, "chunks": []}

            document_json = self._as_dict(doc_row.get("document_json"))
            document = {
                "parsed_document_id": document_json.get("parsed_document_id", f"pd_{file_id}"),
                "file_id": file_id,
                "parse_status": document_json.get("parse_status", "parsed_success"),
                "file_type": doc_row.get("file_type", ""),
                "title": doc_row.get("title", ""),
                "source": doc_row.get("source", ""),
                "authors": self._as_list(doc_row.get("authors_json")),
                "year": doc_row.get("year"),
                "doi": doc_row.get("doi", ""),
                "page_range": doc_row.get("page_range", ""),
                "raw_text": document_json.get("raw_text", ""),
                "metadata_json": self._as_dict(document_json.get("metadata_json", {})),
                "paragraphs": self._as_list(document_json.get("paragraphs", [])),
                "sentences": self._as_list(document_json.get("sentences", [])),
                "table_cells": self._as_list(document_json.get("table_cells", [])),
                "table_rows": self._as_list(document_json.get("table_rows", [])),
                "figure_captions": self._as_list(document_json.get("figure_captions", [])),
                "heading_levels": self._as_list(document_json.get("heading_levels", [])),
                "ocr_blocks": self._as_list(document_json.get("ocr_blocks", [])),
                "parser_name": doc_row.get("parser_name", ""),
                "parser_version": doc_row.get("parser_version", ""),
                "created_at": self._ts(doc_row.get("created_at")),
            }
            chunks = []
            for row in chunk_rows:
                loc = self._as_dict(row.get("source_location_json"))
                chunks.append(
                    {
                        "chunk_id": row.get("chunk_id", ""),
                        "file_id": row.get("file_id", ""),
                        "chunk_type": row.get("chunk_type", "paragraph"),
                        "chunk_index": loc.get("chunk_index", 0),
                        "text_content": row.get("chunk_text", ""),
                        "page_no": loc.get("page_no"),
                        "source_ref": loc.get("source_ref", ""),
                        "extra_json": self._as_dict(row.get("metadata_json")),
                    }
                )
            return {"document": document, "chunks": chunks}

        return self._load_json().get("parsed_documents", {}).get(file_id, {"document": {}, "chunks": []})

    def _put_parsed_pg(self, doc: Dict[str, Any], chunks: List[Dict[str, Any]]) -> None:
        file_id = doc.get("file_id", "")
        document_json = {
            "parsed_document_id": doc.get("parsed_document_id", ""),
            "parse_status": doc.get("parse_status", ""),
            "raw_text": doc.get("raw_text", ""),
            "metadata_json": doc.get("metadata_json", {}),
            "paragraphs": doc.get("paragraphs", []),
            "sentences": doc.get("sentences", []),
            "table_cells": doc.get("table_cells", []),
            "table_rows": doc.get("table_rows", []),
            "figure_captions": doc.get("figure_captions", []),
            "heading_levels": doc.get("heading_levels", []),
            "ocr_blocks": doc.get("ocr_blocks", []),
        }
        created_at = doc.get("created_at") or utc_now_iso()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into {self._schema}.parsed_document (
                      file_id, title, file_type, source, authors_json, year, doi, page_range,
                      parser_name, parser_version, document_json, created_at
                    ) values (
                      %(file_id)s, %(title)s, %(file_type)s, %(source)s, %(authors_json)s::jsonb, %(year)s, %(doi)s, %(page_range)s,
                      %(parser_name)s, %(parser_version)s, %(document_json)s::jsonb, %(created_at)s
                    )
                    on conflict (file_id) do update set
                      title=excluded.title,
                      file_type=excluded.file_type,
                      source=excluded.source,
                      authors_json=excluded.authors_json,
                      year=excluded.year,
                      doi=excluded.doi,
                      page_range=excluded.page_range,
                      parser_name=excluded.parser_name,
                      parser_version=excluded.parser_version,
                      document_json=excluded.document_json,
                      created_at=excluded.created_at
                    """,
                    {
                        "file_id": file_id,
                        "title": doc.get("title", ""),
                        "file_type": doc.get("file_type", ""),
                        "source": doc.get("source", ""),
                        "authors_json": self._to_json(doc.get("authors", []), []),
                        "year": doc.get("year"),
                        "doi": doc.get("doi", ""),
                        "page_range": doc.get("page_range", ""),
                        "parser_name": doc.get("parser_name", ""),
                        "parser_version": doc.get("parser_version", ""),
                        "document_json": self._to_json(document_json, {}),
                        "created_at": created_at,
                    },
                )
                cur.execute(f"delete from {self._schema}.content_chunk where file_id=%s", (file_id,))
                for c in chunks:
                    cur.execute(
                        f"""
                        insert into {self._schema}.content_chunk (
                          chunk_id, file_id, chunk_type, chunk_text, source_location_json, metadata_json, created_at
                        ) values (
                          %(chunk_id)s, %(file_id)s, %(chunk_type)s, %(chunk_text)s,
                          %(source_location_json)s::jsonb, %(metadata_json)s::jsonb, %(created_at)s
                        )
                        on conflict (chunk_id) do update set
                          chunk_type=excluded.chunk_type,
                          chunk_text=excluded.chunk_text,
                          source_location_json=excluded.source_location_json,
                          metadata_json=excluded.metadata_json
                        """,
                        {
                            "chunk_id": c.get("chunk_id", ""),
                            "file_id": file_id,
                            "chunk_type": c.get("chunk_type", "paragraph"),
                            "chunk_text": c.get("text_content", ""),
                            "source_location_json": self._to_json(
                                {
                                    "chunk_index": c.get("chunk_index"),
                                    "page_no": c.get("page_no"),
                                    "source_ref": c.get("source_ref", ""),
                                },
                                {},
                            ),
                            "metadata_json": self._to_json(c.get("extra_json", {}), {}),
                            "created_at": created_at,
                        },
                    )
            conn.commit()

    # candidate region + review record
    def put_region_candidates(self, file_id: str, rows: Iterable[Any], lane: str = "local") -> None:
        items = [self._to_dict(r) for r in rows]
        for it in items:
            it["lane"] = lane
        if self._pg_enabled:
            try:
                self._put_region_candidates_pg(file_id, items, lane=lane)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"put_region_candidates fallback: {exc}", "warning")
        state = self._load_json()
        kept = [
            r
            for r in state.get("candidate_regions", [])
            if not (r.get("file_id") == file_id and r.get("lane", "local") == lane)
        ]
        state["candidate_regions"] = kept + items
        self._save_json(state)

    def list_region_candidates(self, file_id: str = "", lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                sql = f"select * from {self._schema}.candidate_region"
                params: List[Any] = []
                conds: List[str] = []
                if file_id:
                    conds.append("file_id=%s")
                    params.append(file_id)
                if lane is not None:
                    conds.append("lane=%s")
                    params.append(lane)
                if conds:
                    sql += " where " + " and ".join(conds)
                sql += " order by created_at desc"
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        rows = cur.fetchall()
                return [self._row_to_candidate(r) for r in rows]
            except Exception as exc:
                self._event("pg_read_failed", f"list_region_candidates fallback: {exc}", "warning")
        rows = self._load_json().get("candidate_regions", [])
        out = [r for r in rows if (not file_id or r.get("file_id") == file_id)]
        if lane is not None:
            out = [r for r in out if r.get("lane", "local") == lane]
        return [self._row_to_candidate(r) for r in out]

    def get_region_candidates(self, file_id: str, lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        return self.list_region_candidates(file_id, lane=lane)

    def get_region_candidate(self, candidate_id: str) -> Dict[str, Any] | None:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.candidate_region where id=%s", (candidate_id,))
                        row = cur.fetchone()
                return self._row_to_candidate(row) if row else None
            except Exception as exc:
                self._event("pg_read_failed", f"get_region_candidate fallback: {exc}", "warning")
        for row in self._load_json().get("candidate_regions", []):
            if row.get("id") == candidate_id:
                return self._row_to_candidate(row)
        return None

    def update_region_candidate(self, candidate_id: str, **kwargs: Any) -> Dict[str, Any]:
        if self._pg_enabled:
            try:
                self._update_region_candidate_pg(candidate_id, kwargs)
                return self.get_region_candidate(candidate_id) or {}
            except Exception as exc:
                self._event("pg_write_failed", f"update_region_candidate fallback: {exc}", "warning")
        state = self._load_json()
        out: Dict[str, Any] = {}
        new_rows = []
        for row in state.get("candidate_regions", []):
            if row.get("id") == candidate_id:
                row.update(kwargs)
                out = row
            new_rows.append(row)
        state["candidate_regions"] = new_rows
        self._save_json(state)
        return self._row_to_candidate(out) if out else {}

    def delete_region_candidate(self, candidate_id: str) -> bool:
        """按主键删除一条脑区候选（用于合并重复名称等场景）。"""
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"delete from {self._schema}.candidate_region where id=%s", (candidate_id,))
                    conn.commit()
                return True
            except Exception as exc:
                self._event("pg_write_failed", f"delete_region_candidate fallback: {exc}", "warning")
        state = self._load_json()
        state["candidate_regions"] = [r for r in state.get("candidate_regions", []) if r.get("id") != candidate_id]
        self._save_json(state)
        return True

    def append_review_record(self, record: Any) -> None:
        payload = self._to_dict(record)
        if self._pg_enabled:
            try:
                self._append_review_pg(payload)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"append_review_record fallback: {exc}", "warning")
        state = self._load_json()
        state.setdefault("review_records", []).append(payload)
        self._save_json(state)

    def list_review_records(self) -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.review_record order by created_at desc")
                        rows = cur.fetchall()
                return [
                    {
                        "id": r.get("id", ""),
                        "candidate_region_id": r.get("candidate_region_id", ""),
                        "reviewer": r.get("reviewer", ""),
                        "action": r.get("action", ""),
                        "before_json": self._as_dict(r.get("before_json")),
                        "after_json": self._as_dict(r.get("after_json")),
                        "note": r.get("note", ""),
                        "created_at": self._ts(r.get("created_at")),
                    }
                    for r in rows
                ]
            except Exception as exc:
                self._event("pg_read_failed", f"list_review_records fallback: {exc}", "warning")
        return self._load_json().get("review_records", [])

    def _put_region_candidates_pg(self, file_id: str, rows: List[Dict[str, Any]], lane: str = "local") -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"delete from {self._schema}.candidate_region where file_id=%s and lane=%s",
                    (file_id, lane),
                )
                for r in rows:
                    cur.execute(
                        f"""
                        insert into {self._schema}.candidate_region (
                          id, file_id, parsed_document_id, chunk_id, source_text,
                          en_name_candidate, cn_name_candidate, alias_candidates,
                          laterality_candidate, region_category_candidate, granularity_candidate,
                          parent_region_candidate, ontology_source_candidate,
                          confidence, extraction_method, llm_model,
                          status, review_note, created_at, updated_at, lane
                        ) values (
                          %(id)s, %(file_id)s, %(parsed_document_id)s, %(chunk_id)s, %(source_text)s,
                          %(en_name_candidate)s, %(cn_name_candidate)s, %(alias_candidates)s::jsonb,
                          %(laterality_candidate)s, %(region_category_candidate)s, %(granularity_candidate)s,
                          %(parent_region_candidate)s, %(ontology_source_candidate)s,
                          %(confidence)s, %(extraction_method)s, %(llm_model)s,
                          %(status)s, %(review_note)s, %(created_at)s, %(updated_at)s, %(lane)s
                        )
                        """,
                        {
                            "id": r.get("id", ""),
                            "file_id": file_id,
                            "parsed_document_id": r.get("parsed_document_id", ""),
                            "chunk_id": r.get("chunk_id", ""),
                            "source_text": r.get("source_text", ""),
                            "en_name_candidate": r.get("en_name_candidate", ""),
                            "cn_name_candidate": r.get("cn_name_candidate", ""),
                            "alias_candidates": self._to_json(r.get("alias_candidates", []), []),
                            "laterality_candidate": r.get("laterality_candidate", "unknown"),
                            "region_category_candidate": r.get("region_category_candidate", "brain_region"),
                            "granularity_candidate": r.get("granularity_candidate", "unknown"),
                            "parent_region_candidate": r.get("parent_region_candidate", ""),
                            "ontology_source_candidate": r.get("ontology_source_candidate", "workbench"),
                            "confidence": float(r.get("confidence", 0.0)),
                            "extraction_method": r.get("extraction_method", "local_rule"),
                            "llm_model": r.get("llm_model", ""),
                            "status": r.get("status", "pending_review"),
                            "review_note": r.get("review_note", ""),
                            "created_at": r.get("created_at") or utc_now_iso(),
                            "updated_at": r.get("updated_at") or utc_now_iso(),
                            "lane": r.get("lane", lane),
                        },
                    )
            conn.commit()

    def _update_region_candidate_pg(self, candidate_id: str, patch: Dict[str, Any]) -> None:
        mapping = {
            "source_text": "source_text",
            "en_name_candidate": "en_name_candidate",
            "cn_name_candidate": "cn_name_candidate",
            "alias_candidates": "alias_candidates",
            "laterality_candidate": "laterality_candidate",
            "region_category_candidate": "region_category_candidate",
            "granularity_candidate": "granularity_candidate",
            "parent_region_candidate": "parent_region_candidate",
            "ontology_source_candidate": "ontology_source_candidate",
            "confidence": "confidence",
            "review_note": "review_note",
            "status": "status",
            "updated_at": "updated_at",
        }
        sets = []
        params = {"id": candidate_id}
        for k, v in patch.items():
            col = mapping.get(k)
            if not col:
                continue
            if col == "alias_candidates":
                sets.append(f"{col}=%({col})s::jsonb")
                params[col] = self._to_json(v, [])
            else:
                sets.append(f"{col}=%({col})s")
                params[col] = v
        if not sets:
            return
        if "updated_at" not in params:
            params["updated_at"] = utc_now_iso()
            sets.append("updated_at=%(updated_at)s")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"update {self._schema}.candidate_region set {', '.join(sets)} where id=%(id)s", params)
            conn.commit()

    def _append_review_pg(self, payload: Dict[str, Any]) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into {self._schema}.review_record (id, candidate_region_id, reviewer, action, before_json, after_json, note, created_at)
                    values (%(id)s, %(candidate_region_id)s, %(reviewer)s, %(action)s, %(before_json)s::jsonb, %(after_json)s::jsonb, %(note)s, %(created_at)s)
                    on conflict (id) do update set
                      reviewer=excluded.reviewer,
                      action=excluded.action,
                      before_json=excluded.before_json,
                      after_json=excluded.after_json,
                      note=excluded.note,
                      created_at=excluded.created_at
                    """,
                    {
                        "id": payload.get("id", ""),
                        "candidate_region_id": payload.get("candidate_region_id", ""),
                        "reviewer": payload.get("reviewer", "user"),
                        "action": payload.get("action", "edit"),
                        "before_json": self._to_json(payload.get("before_json", {}), {}),
                        "after_json": self._to_json(payload.get("after_json", {}), {}),
                        "note": payload.get("note", ""),
                        "created_at": payload.get("created_at") or utc_now_iso(),
                    },
                )
            conn.commit()

    def _row_to_candidate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        en = row.get("en_name_candidate", "")
        cn = row.get("cn_name_candidate", "")
        note = row.get("review_note", "")
        return {
            "id": row.get("id", ""),
            "global_region_id": derive_global_region_id_for_row(note, en, cn),
            "file_id": row.get("file_id", ""),
            "parsed_document_id": row.get("parsed_document_id", ""),
            "lane": row.get("lane", "local"),
            "chunk_id": row.get("chunk_id", ""),
            "source_text": row.get("source_text", ""),
            "en_name_candidate": en,
            "cn_name_candidate": cn,
            "alias_candidates": self._as_list(row.get("alias_candidates")),
            "laterality_candidate": row.get("laterality_candidate", "unknown"),
            "region_category_candidate": row.get("region_category_candidate", "brain_region"),
            "granularity_candidate": row.get("granularity_candidate", "unknown"),
            "parent_region_candidate": row.get("parent_region_candidate", ""),
            "ontology_source_candidate": row.get("ontology_source_candidate", "workbench"),
            "confidence": float(row.get("confidence") or 0),
            "extraction_method": row.get("extraction_method", "local_rule"),
            "llm_model": row.get("llm_model", ""),
            "status": row.get("status", "pending_review"),
            "review_note": note,
            "created_at": self._ts(row.get("created_at")),
            "updated_at": self._ts(row.get("updated_at")),
        }

    # connection candidates
    def put_connection_candidates(self, file_id: str, rows: Iterable[Any], lane: str = "local") -> None:
        items = [self._to_dict(x) for x in rows]
        for it in items:
            it["lane"] = lane
        if self._pg_enabled:
            try:
                self._put_connection_candidates_pg(file_id, items, lane=lane)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"put_connection_candidates fallback: {exc}", "warning")
        state = self._load_json()
        kept = [
            r
            for r in state.get("candidate_connections", [])
            if not (r.get("file_id") == file_id and r.get("lane", "local") == lane)
        ]
        state["candidate_connections"] = kept + items
        self._save_json(state)

    def list_connection_candidates(self, file_id: str = "", lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                sql = f"select * from {self._schema}.candidate_connection"
                params: List[Any] = []
                conds: List[str] = []
                if file_id:
                    conds.append("file_id=%s")
                    params.append(file_id)
                if lane is not None:
                    conds.append("lane=%s")
                    params.append(lane)
                if conds:
                    sql += " where " + " and ".join(conds)
                sql += " order by updated_at desc"
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        rows = cur.fetchall()
                return [self._row_to_connection_candidate(r) for r in rows]
            except Exception as exc:
                self._event("pg_read_failed", f"list_connection_candidates fallback: {exc}", "warning")
        rows = self._load_json().get("candidate_connections", [])
        if file_id:
            rows = [r for r in rows if r.get("file_id") == file_id]
        if lane is not None:
            rows = [r for r in rows if r.get("lane", "local") == lane]
        return rows

    def get_connection_candidates(self, file_id: str, lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        return self.list_connection_candidates(file_id, lane=lane)

    def get_connection_candidate(self, connection_id: str) -> Dict[str, Any] | None:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.candidate_connection where connection_id=%s", (connection_id,))
                        row = cur.fetchone()
                return self._row_to_connection_candidate(row) if row else None
            except Exception as exc:
                self._event("pg_read_failed", f"get_connection_candidate fallback: {exc}", "warning")
        for row in self._load_json().get("candidate_connections", []):
            if row.get("id") == connection_id:
                return row
        return None

    def update_connection_candidate(self, connection_id: str, **kwargs: Any) -> Dict[str, Any]:
        if self._pg_enabled:
            try:
                self._update_connection_candidate_pg(connection_id, kwargs)
                return self.get_connection_candidate(connection_id) or {}
            except Exception as exc:
                self._event("pg_write_failed", f"update_connection_candidate fallback: {exc}", "warning")
        state = self._load_json()
        out: Dict[str, Any] = {}
        rows = []
        for row in state.get("candidate_connections", []):
            if row.get("id") == connection_id:
                row.update(kwargs)
                out = row
            rows.append(row)
        state["candidate_connections"] = rows
        self._save_json(state)
        return out

    def _put_connection_candidates_pg(self, file_id: str, rows: List[Dict[str, Any]], lane: str = "local") -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"delete from {self._schema}.candidate_connection where file_id=%s and lane=%s",
                    (file_id, lane),
                )
                for r in rows:
                    connection_id = r.get("id", "") or r.get("connection_id", "")
                    cur.execute(
                        f"""
                        insert into {self._schema}.candidate_connection (
                          connection_id, file_id, source_region, target_region, directionality, confidence, evidence_chunk_ids,
                          parsed_document_id, source_text, en_name_candidate, cn_name_candidate, alias_candidates, description_candidate,
                          granularity_candidate, connection_modality_candidate, source_region_ref_candidate, target_region_ref_candidate,
                          direction_label, extraction_method, llm_model, status, review_note, created_at, updated_at, lane
                        ) values (
                          %(connection_id)s, %(file_id)s, %(source_region)s, %(target_region)s, %(directionality)s, %(confidence)s, %(evidence_chunk_ids)s::jsonb,
                          %(parsed_document_id)s, %(source_text)s, %(en_name_candidate)s, %(cn_name_candidate)s, %(alias_candidates)s::jsonb, %(description_candidate)s,
                          %(granularity_candidate)s, %(connection_modality_candidate)s, %(source_region_ref_candidate)s, %(target_region_ref_candidate)s,
                          %(direction_label)s, %(extraction_method)s, %(llm_model)s, %(status)s, %(review_note)s, %(created_at)s, %(updated_at)s, %(lane)s
                        )
                        """,
                        {
                            "connection_id": connection_id,
                            "file_id": file_id,
                            "source_region": r.get("source_region_ref_candidate", ""),
                            "target_region": r.get("target_region_ref_candidate", ""),
                            "directionality": r.get("direction_label", "unknown"),
                            "confidence": float(r.get("confidence", 0.0)),
                            "evidence_chunk_ids": self._to_json([], []),
                            "parsed_document_id": r.get("parsed_document_id", ""),
                            "source_text": r.get("source_text", ""),
                            "en_name_candidate": r.get("en_name_candidate", ""),
                            "cn_name_candidate": r.get("cn_name_candidate", ""),
                            "alias_candidates": self._to_json(r.get("alias_candidates", []), []),
                            "description_candidate": r.get("description_candidate", ""),
                            "granularity_candidate": r.get("granularity_candidate", "unknown"),
                            "connection_modality_candidate": r.get("connection_modality_candidate", "unknown"),
                            "source_region_ref_candidate": r.get("source_region_ref_candidate", ""),
                            "target_region_ref_candidate": r.get("target_region_ref_candidate", ""),
                            "direction_label": r.get("direction_label", "unknown"),
                            "extraction_method": r.get("extraction_method", "local_rule"),
                            "llm_model": r.get("llm_model", ""),
                            "status": r.get("status", "pending_review"),
                            "review_note": r.get("review_note", ""),
                            "created_at": r.get("created_at") or utc_now_iso(),
                            "updated_at": r.get("updated_at") or utc_now_iso(),
                            "lane": r.get("lane", lane),
                        },
                    )
            conn.commit()

    def _update_connection_candidate_pg(self, connection_id: str, patch: Dict[str, Any]) -> None:
        mapping = {
            "source_text": "source_text",
            "en_name_candidate": "en_name_candidate",
            "cn_name_candidate": "cn_name_candidate",
            "alias_candidates": "alias_candidates",
            "description_candidate": "description_candidate",
            "granularity_candidate": "granularity_candidate",
            "connection_modality_candidate": "connection_modality_candidate",
            "source_region_ref_candidate": "source_region_ref_candidate",
            "target_region_ref_candidate": "target_region_ref_candidate",
            "direction_label": "direction_label",
            "confidence": "confidence",
            "extraction_method": "extraction_method",
            "llm_model": "llm_model",
            "status": "status",
            "review_note": "review_note",
            "updated_at": "updated_at",
        }
        sets = []
        params = {"connection_id": connection_id}
        for k, v in patch.items():
            col = mapping.get(k)
            if not col:
                continue
            if col == "alias_candidates":
                sets.append(f"{col}=%({col})s::jsonb")
                params[col] = self._to_json(v, [])
            else:
                sets.append(f"{col}=%({col})s")
                params[col] = v
        if not sets:
            return
        if "updated_at" not in params:
            params["updated_at"] = utc_now_iso()
            sets.append("updated_at=%(updated_at)s")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"update {self._schema}.candidate_connection set {', '.join(sets)} where connection_id=%(connection_id)s", params)
            conn.commit()

    def _row_to_connection_candidate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("connection_id", ""),
            "file_id": row.get("file_id", ""),
            "parsed_document_id": row.get("parsed_document_id", ""),
            "lane": row.get("lane", "local"),
            "source_text": row.get("source_text", ""),
            "en_name_candidate": row.get("en_name_candidate", ""),
            "cn_name_candidate": row.get("cn_name_candidate", ""),
            "alias_candidates": self._as_list(row.get("alias_candidates")),
            "description_candidate": row.get("description_candidate", ""),
            "granularity_candidate": row.get("granularity_candidate", "unknown"),
            "connection_modality_candidate": row.get("connection_modality_candidate", "unknown"),
            "source_region_ref_candidate": row.get("source_region_ref_candidate", row.get("source_region", "")),
            "target_region_ref_candidate": row.get("target_region_ref_candidate", row.get("target_region", "")),
            "confidence": float(row.get("confidence") or 0),
            "direction_label": row.get("direction_label", row.get("directionality", "unknown")),
            "extraction_method": row.get("extraction_method", "local_rule"),
            "llm_model": row.get("llm_model", ""),
            "status": row.get("status", "pending_review"),
            "review_note": row.get("review_note", ""),
            "created_at": self._ts(row.get("created_at")),
            "updated_at": self._ts(row.get("updated_at")),
        }

    # circuit candidates
    def put_circuit_candidates(self, file_id: str, rows: Iterable[Any], lane: str = "local") -> None:
        items = [self._to_dict(x) for x in rows]
        for it in items:
            it["lane"] = lane
        if self._pg_enabled:
            try:
                self._put_circuit_candidates_pg(file_id, items, lane=lane)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"put_circuit_candidates fallback: {exc}", "warning")
        state = self._load_json()
        kept = [
            r
            for r in state.get("candidate_circuits", [])
            if not (r.get("file_id") == file_id and r.get("lane", "local") == lane)
        ]
        state["candidate_circuits"] = kept + items
        self._save_json(state)

    def list_circuit_candidates(self, file_id: str = "", lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                sql = f"select * from {self._schema}.candidate_circuit"
                params: List[Any] = []
                conds: List[str] = []
                if file_id:
                    conds.append("file_id=%s")
                    params.append(file_id)
                if lane is not None:
                    conds.append("lane=%s")
                    params.append(lane)
                if conds:
                    sql += " where " + " and ".join(conds)
                sql += " order by updated_at desc"
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        rows = cur.fetchall()
                        out: List[Dict[str, Any]] = []
                        for row in rows:
                            cid = row.get("circuit_id", "")
                            cur.execute(
                                f"select * from {self._schema}.candidate_circuit_node where candidate_circuit_id=%s order by node_order, created_at",
                                (cid,),
                            )
                            nodes = [self._row_to_circuit_node(n) for n in cur.fetchall()]
                            out.append(self._row_to_circuit_candidate(row, nodes))
                return out
            except Exception as exc:
                self._event("pg_read_failed", f"list_circuit_candidates fallback: {exc}", "warning")
        rows = self._load_json().get("candidate_circuits", [])
        if file_id:
            rows = [r for r in rows if r.get("file_id") == file_id]
        if lane is not None:
            rows = [r for r in rows if r.get("lane", "local") == lane]
        return rows

    def get_circuit_candidates(self, file_id: str, lane: Optional[str] = "local") -> List[Dict[str, Any]]:
        return self.list_circuit_candidates(file_id, lane=lane)

    def get_circuit_candidate(self, circuit_id: str) -> Dict[str, Any] | None:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.candidate_circuit where circuit_id=%s", (circuit_id,))
                        row = cur.fetchone()
                        if not row:
                            return None
                        cur.execute(
                            f"select * from {self._schema}.candidate_circuit_node where candidate_circuit_id=%s order by node_order, created_at",
                            (circuit_id,),
                        )
                        nodes = [self._row_to_circuit_node(n) for n in cur.fetchall()]
                return self._row_to_circuit_candidate(row, nodes)
            except Exception as exc:
                self._event("pg_read_failed", f"get_circuit_candidate fallback: {exc}", "warning")
        for row in self._load_json().get("candidate_circuits", []):
            if row.get("id") == circuit_id:
                return row
        return None

    def update_circuit_candidate(self, circuit_id: str, **kwargs: Any) -> Dict[str, Any]:
        if self._pg_enabled:
            try:
                self._update_circuit_candidate_pg(circuit_id, kwargs)
                return self.get_circuit_candidate(circuit_id) or {}
            except Exception as exc:
                self._event("pg_write_failed", f"update_circuit_candidate fallback: {exc}", "warning")
        state = self._load_json()
        out: Dict[str, Any] = {}
        rows = []
        for row in state.get("candidate_circuits", []):
            if row.get("id") == circuit_id:
                row.update(kwargs)
                out = row
            rows.append(row)
        state["candidate_circuits"] = rows
        self._save_json(state)
        return out

    def _put_circuit_candidates_pg(self, file_id: str, rows: List[Dict[str, Any]], lane: str = "local") -> None:
        def _node_order(value: Any) -> int:
            if value is None or value == "":
                return 1
            try:
                return int(value)
            except Exception:
                return 1

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"select circuit_id from {self._schema}.candidate_circuit where file_id=%s and lane=%s",
                    (file_id, lane),
                )
                existing = [r.get("circuit_id", "") for r in cur.fetchall()]
                if existing:
                    cur.execute(
                        f"delete from {self._schema}.candidate_circuit_node where candidate_circuit_id = any(%s::text[])",
                        (existing,),
                    )
                cur.execute(
                    f"delete from {self._schema}.candidate_circuit where file_id=%s and lane=%s",
                    (file_id, lane),
                )
                for r in rows:
                    circuit_id = r.get("id", "") or r.get("circuit_id", "")
                    nodes = r.get("nodes", []) or []
                    cur.execute(
                        f"""
                        insert into {self._schema}.candidate_circuit (
                          circuit_id, circuit_name, circuit_family, confidence, evidence_chunk_ids,
                          file_id, parsed_document_id, source_text,
                          en_name_candidate, cn_name_candidate, alias_candidates, description_candidate,
                          circuit_kind_candidate, loop_type_candidate, cycle_verified_candidate,
                          confidence_circuit, granularity_candidate, extraction_method, llm_model,
                          status, review_note, nodes, created_at, updated_at, lane
                        ) values (
                          %(circuit_id)s, %(circuit_name)s, %(circuit_family)s, %(confidence)s, %(evidence_chunk_ids)s::jsonb,
                          %(file_id)s, %(parsed_document_id)s, %(source_text)s,
                          %(en_name_candidate)s, %(cn_name_candidate)s, %(alias_candidates)s::jsonb, %(description_candidate)s,
                          %(circuit_kind_candidate)s, %(loop_type_candidate)s, %(cycle_verified_candidate)s,
                          %(confidence_circuit)s, %(granularity_candidate)s, %(extraction_method)s, %(llm_model)s,
                          %(status)s, %(review_note)s, %(nodes_json)s::jsonb, %(created_at)s, %(updated_at)s, %(lane)s
                        )
                        """,
                        {
                            "circuit_id": circuit_id,
                            "circuit_name": r.get("en_name_candidate") or r.get("cn_name_candidate") or circuit_id,
                            "circuit_family": r.get("circuit_kind_candidate", "unknown"),
                            "confidence": float(r.get("confidence_circuit", 0.0)),
                            "evidence_chunk_ids": self._to_json([], []),
                            "file_id": file_id,
                            "parsed_document_id": r.get("parsed_document_id", ""),
                            "source_text": r.get("source_text", ""),
                            "en_name_candidate": r.get("en_name_candidate", ""),
                            "cn_name_candidate": r.get("cn_name_candidate", ""),
                            "alias_candidates": self._to_json(r.get("alias_candidates", []), []),
                            "description_candidate": r.get("description_candidate", ""),
                            "circuit_kind_candidate": r.get("circuit_kind_candidate", "unknown"),
                            "loop_type_candidate": r.get("loop_type_candidate", "inferred"),
                            "cycle_verified_candidate": bool(r.get("cycle_verified_candidate", False)),
                            "confidence_circuit": float(r.get("confidence_circuit", 0.0)),
                            "granularity_candidate": r.get("granularity_candidate", "unknown"),
                            "extraction_method": r.get("extraction_method", "local_rule"),
                            "llm_model": r.get("llm_model", ""),
                            "status": r.get("status", "pending_review"),
                            "review_note": r.get("review_note", ""),
                            "nodes_json": self._to_json(nodes, []),
                            "created_at": r.get("created_at") or utc_now_iso(),
                            "updated_at": r.get("updated_at") or utc_now_iso(),
                            "lane": r.get("lane", lane),
                        },
                    )
                    for n in nodes:
                        cur.execute(
                            f"""
                            insert into {self._schema}.candidate_circuit_node (
                              id, candidate_circuit_id, file_id, region_id_candidate, granularity_candidate, node_order, role_label, created_at
                            ) values (
                              %(id)s, %(candidate_circuit_id)s, %(file_id)s, %(region_id_candidate)s, %(granularity_candidate)s, %(node_order)s, %(role_label)s, %(created_at)s
                            )
                            """,
                            {
                                "id": n.get("id") or n.get("node_id") or f"{circuit_id}_node_{n.get('node_order', 1)}",
                                "candidate_circuit_id": circuit_id,
                                "file_id": file_id,
                                "region_id_candidate": n.get("region_id_candidate", ""),
                                "granularity_candidate": n.get("granularity_candidate", r.get("granularity_candidate", "unknown")),
                                "node_order": _node_order(n.get("node_order", 1)),
                                "role_label": n.get("role_label", ""),
                                "created_at": n.get("created_at") or utc_now_iso(),
                            },
                        )
            conn.commit()

    def _update_circuit_candidate_pg(self, circuit_id: str, patch: Dict[str, Any]) -> None:
        mapping = {
            "source_text": "source_text",
            "en_name_candidate": "en_name_candidate",
            "cn_name_candidate": "cn_name_candidate",
            "alias_candidates": "alias_candidates",
            "description_candidate": "description_candidate",
            "circuit_kind_candidate": "circuit_kind_candidate",
            "loop_type_candidate": "loop_type_candidate",
            "cycle_verified_candidate": "cycle_verified_candidate",
            "confidence_circuit": "confidence_circuit",
            "granularity_candidate": "granularity_candidate",
            "status": "status",
            "review_note": "review_note",
            "updated_at": "updated_at",
        }
        sets = []
        params = {"circuit_id": circuit_id}
        with self._conn() as conn:
            with conn.cursor() as cur:
                for k, v in patch.items():
                    col = mapping.get(k)
                    if not col:
                        continue
                    if col == "alias_candidates":
                        sets.append(f"{col}=%({col})s::jsonb")
                        params[col] = self._to_json(v, [])
                    else:
                        sets.append(f"{col}=%({col})s")
                        params[col] = v
                if "updated_at" not in params:
                    params["updated_at"] = utc_now_iso()
                    sets.append("updated_at=%(updated_at)s")
                if sets:
                    cur.execute(
                        f"update {self._schema}.candidate_circuit set {', '.join(sets)} where circuit_id=%(circuit_id)s",
                        params,
                    )
                if "nodes" in patch:
                    def _node_order(value: Any) -> int:
                        if value is None or value == "":
                            return 1
                        try:
                            return int(value)
                        except Exception:
                            return 1

                    nodes = patch.get("nodes", []) or []
                    cur.execute(f"update {self._schema}.candidate_circuit set nodes=%s::jsonb where circuit_id=%s", (self._to_json(nodes, []), circuit_id))
                    cur.execute(f"delete from {self._schema}.candidate_circuit_node where candidate_circuit_id=%s", (circuit_id,))
                    for n in nodes:
                        cur.execute(
                            f"""
                            insert into {self._schema}.candidate_circuit_node (
                              id, candidate_circuit_id, file_id, region_id_candidate, granularity_candidate, node_order, role_label, created_at
                            )
                            select
                              %s, %s, coalesce((select file_id from {self._schema}.candidate_circuit where circuit_id=%s), ''), %s, %s, %s, %s, %s
                            """,
                            (
                                n.get("id") or n.get("node_id") or f"{circuit_id}_node_{n.get('node_order', 1)}",
                                circuit_id,
                                circuit_id,
                                n.get("region_id_candidate", ""),
                                n.get("granularity_candidate", "unknown"),
                                _node_order(n.get("node_order", 1)),
                                n.get("role_label", ""),
                                n.get("created_at") or utc_now_iso(),
                            ),
                        )
            conn.commit()

    def _row_to_circuit_node(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id", ""),
            "candidate_circuit_id": row.get("candidate_circuit_id", ""),
            "file_id": row.get("file_id", ""),
            "region_id_candidate": row.get("region_id_candidate", ""),
            "granularity_candidate": row.get("granularity_candidate", "unknown"),
            "node_order": int(row.get("node_order")) if row.get("node_order") is not None else 1,
            "role_label": row.get("role_label", ""),
            "created_at": self._ts(row.get("created_at")),
        }

    def _row_to_circuit_candidate(self, row: Dict[str, Any], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "id": row.get("circuit_id", ""),
            "file_id": row.get("file_id", ""),
            "parsed_document_id": row.get("parsed_document_id", ""),
            "lane": row.get("lane", "local"),
            "source_text": row.get("source_text", ""),
            "en_name_candidate": row.get("en_name_candidate", ""),
            "cn_name_candidate": row.get("cn_name_candidate", ""),
            "alias_candidates": self._as_list(row.get("alias_candidates")),
            "description_candidate": row.get("description_candidate", ""),
            "circuit_kind_candidate": row.get("circuit_kind_candidate", "unknown"),
            "loop_type_candidate": row.get("loop_type_candidate", "inferred"),
            "cycle_verified_candidate": bool(row.get("cycle_verified_candidate", False)),
            "confidence_circuit": float(row.get("confidence_circuit") or 0),
            "granularity_candidate": row.get("granularity_candidate", "unknown"),
            "extraction_method": row.get("extraction_method", "local_rule"),
            "llm_model": row.get("llm_model", ""),
            "status": row.get("status", "pending_review"),
            "review_note": row.get("review_note", ""),
            "nodes": nodes if nodes else self._as_list(row.get("nodes")),
            "circuit_name": row.get("circuit_name", ""),
            "circuit_family": row.get("circuit_family", ""),
            "created_at": self._ts(row.get("created_at")),
            "updated_at": self._ts(row.get("updated_at")),
        }
    # task + logs
    def put_task(self, task: Any) -> None:
        payload = self._to_dict(task)
        if self._pg_enabled:
            try:
                self._put_task_pg(payload)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"put_task fallback: {exc}", "warning")
        state = self._load_json()
        state.setdefault("tasks", {})[payload["task_id"]] = payload
        self._save_json(state)

    def get_task(self, task_id: str) -> Dict[str, Any] | None:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.task_run where task_id=%s", (task_id,))
                        row = cur.fetchone()
                return self._row_to_task(row) if row else None
            except Exception as exc:
                self._event("pg_read_failed", f"get_task fallback: {exc}", "warning")
        return self._load_json().get("tasks", {}).get(task_id)

    def update_task(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        if self._pg_enabled:
            try:
                current = self.get_task(task_id) or {}
                current.update(kwargs)
                self._put_task_pg(current)
                return self.get_task(task_id) or {}
            except Exception as exc:
                self._event("pg_write_failed", f"update_task fallback: {exc}", "warning")
        state = self._load_json()
        row = state.setdefault("tasks", {}).get(task_id, {})
        row.update(kwargs)
        state["tasks"][task_id] = row
        self._save_json(state)
        return row

    def list_tasks(self) -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select * from {self._schema}.task_run order by created_at desc")
                        rows = cur.fetchall()
                return [self._row_to_task(r) for r in rows]
            except Exception as exc:
                self._event("pg_read_failed", f"list_tasks fallback: {exc}", "warning")
        return list(self._load_json().get("tasks", {}).values())

    def _put_task_pg(self, task: Dict[str, Any]) -> None:
        input_objects = task.get("input_objects", {}) or {}
        # 把进度字段一起放进 parameters_json，不增加 DB 列
        params_json = {
            "parameters": task.get("parameters", {}),
            "trigger_source": task.get("trigger_source", "ui"),
            "model_name": task.get("model_name", ""),
            "created_at": task.get("created_at") or utc_now_iso(),
            "progress_percent": task.get("progress_percent", 0),
            "progress_stage": task.get("progress_stage", ""),
            "progress_message": task.get("progress_message", ""),
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into {self._schema}.task_run (
                      task_id, task_type, status, actor, input_object_json, model_or_rule_version,
                      parameters_json, output_summary_json, error_reason, started_at, ended_at, created_at
                    ) values (
                      %(task_id)s, %(task_type)s, %(status)s, %(actor)s, %(input_object_json)s::jsonb, %(model_or_rule_version)s,
                      %(parameters_json)s::jsonb, %(output_summary_json)s::jsonb, %(error_reason)s, %(started_at)s, %(ended_at)s, %(created_at)s
                    )
                    on conflict (task_id) do update set
                      task_type=excluded.task_type,
                      status=excluded.status,
                      actor=excluded.actor,
                      input_object_json=excluded.input_object_json,
                      model_or_rule_version=excluded.model_or_rule_version,
                      parameters_json=excluded.parameters_json,
                      output_summary_json=excluded.output_summary_json,
                      error_reason=excluded.error_reason,
                      started_at=excluded.started_at,
                      ended_at=excluded.ended_at
                    """,
                    {
                        "task_id": task.get("task_id", ""),
                        "task_type": task.get("task_type", ""),
                        "status": task.get("status", "queued"),
                        "actor": task.get("initiator", ""),
                        "input_object_json": self._to_json(input_objects, {}),
                        "model_or_rule_version": task.get("model_or_rule_version", ""),
                        "parameters_json": self._to_json(params_json, {}),
                        "output_summary_json": self._to_json(task.get("output_summary", {}), {}),
                        "error_reason": task.get("error_reason", ""),
                        "started_at": task.get("started_at") or None,
                        "ended_at": task.get("ended_at") or None,
                        "created_at": task.get("created_at") or utc_now_iso(),
                    },
                )
                cur.execute(
                    f"""
                    insert into {self._schema}.extraction_run (
                      id, file_id, task_type, trigger_source, model_name, params_json,
                      status, started_at, finished_at, summary, error_message
                    ) values (
                      %(id)s, %(file_id)s, %(task_type)s, %(trigger_source)s, %(model_name)s, %(params_json)s::jsonb,
                      %(status)s, %(started_at)s, %(finished_at)s, %(summary)s, %(error_message)s
                    )
                    on conflict (id) do update set
                      file_id=excluded.file_id,
                      task_type=excluded.task_type,
                      trigger_source=excluded.trigger_source,
                      model_name=excluded.model_name,
                      params_json=excluded.params_json,
                      status=excluded.status,
                      started_at=excluded.started_at,
                      finished_at=excluded.finished_at,
                      summary=excluded.summary,
                      error_message=excluded.error_message
                    """,
                    {
                        "id": task.get("task_id", ""),
                        "file_id": input_objects.get("file_id", ""),
                        "task_type": task.get("task_type", ""),
                        "trigger_source": task.get("trigger_source", "ui"),
                        "model_name": task.get("model_name", ""),
                        "params_json": self._to_json(params_json, {}),
                        "status": task.get("status", "queued"),
                        "started_at": task.get("started_at") or None,
                        "finished_at": task.get("ended_at") or None,
                        "summary": self._to_json(task.get("output_summary", {}), {}),
                        "error_message": task.get("error_reason", ""),
                    },
                )
            conn.commit()

    def append_task_log(self, payload: Dict[str, Any]) -> None:
        if self._pg_enabled:
            try:
                self._append_task_log_pg(payload)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"append_task_log fallback: {exc}", "warning")
        state = self._load_json()
        logs = state.setdefault("task_logs", [])
        logs.append(payload)
        state["task_logs"] = logs[-5000:]
        self._save_json(state)

    def list_task_logs(self, run_id: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        if self._pg_enabled:
            try:
                sql = f"select * from {self._schema}.task_log_v2"
                params = []
                if run_id:
                    sql += " where run_id=%s"
                    params.append(run_id)
                sql += " order by created_at desc limit %s"
                params.append(int(limit))
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        rows = cur.fetchall()
                out = []
                for r in reversed(rows):
                    detail = self._as_dict(r.get("detail_json"))
                    out.append(
                        {
                            "log_id": r.get("id", ""),
                            "run_id": r.get("run_id", "-"),
                            "level": r.get("level", "info"),
                            "event_type": r.get("event_type", "log_event"),
                            "module": detail.get("module", "APP"),
                            "message": r.get("message", ""),
                            "detail_json": detail,
                            "created_at": self._ts(r.get("created_at")),
                        }
                    )
                return out
            except Exception as exc:
                self._event("pg_read_failed", f"list_task_logs fallback: {exc}", "warning")

        rows = self._load_json().get("task_logs", [])
        if run_id:
            rows = [r for r in rows if r.get("run_id") == run_id]
        return rows[-limit:]

    def _append_task_log_pg(self, payload: Dict[str, Any]) -> None:
        detail = self._as_dict(payload.get("detail_json"))
        if payload.get("module") and "module" not in detail:
            detail["module"] = payload.get("module")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into {self._schema}.task_log_v2 (id, run_id, level, event_type, message, detail_json, created_at)
                    values (%(id)s, %(run_id)s, %(level)s, %(event_type)s, %(message)s, %(detail_json)s::jsonb, %(created_at)s)
                    """,
                    {
                        "id": payload.get("log_id") or payload.get("id"),
                        "run_id": payload.get("run_id", "-"),
                        "level": payload.get("level", "info"),
                        "event_type": payload.get("event_type", "log_event"),
                        "message": payload.get("message", ""),
                        "detail_json": self._to_json(detail, {}),
                        "created_at": payload.get("created_at") or utc_now_iso(),
                    },
                )
            conn.commit()

    # workspace snapshot
    def get_workspace_snapshot(self) -> Dict[str, Any]:
        if self._pg_enabled:
            try:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"select payload_json from {self._schema}.workspace_snapshot where snapshot_id='default'")
                        row = cur.fetchone()
                return self._as_dict(row.get("payload_json")) if row else {}
            except Exception as exc:
                self._event("pg_read_failed", f"get_workspace_snapshot fallback: {exc}", "warning")
        return self._load_json().get("workspace_snapshot", {})

    def put_workspace_snapshot(self, payload: Dict[str, Any]) -> None:
        if self._pg_enabled:
            try:
                self._put_workspace_snapshot_pg(payload)
                return
            except Exception as exc:
                self._event("pg_write_failed", f"put_workspace_snapshot fallback: {exc}", "warning")
        state = self._load_json()
        state["workspace_snapshot"] = payload
        self._save_json(state)

    def _put_workspace_snapshot_pg(self, payload: Dict[str, Any]) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into {self._schema}.workspace_snapshot (snapshot_id, payload_json, updated_at)
                    values ('default', %(payload)s::jsonb, now())
                    on conflict (snapshot_id) do update set payload_json=excluded.payload_json, updated_at=excluded.updated_at
                    """,
                    {"payload": self._to_json(payload or {}, {})},
                )
            conn.commit()

    def _row_to_task(self, row: Dict[str, Any]) -> Dict[str, Any]:
        params_json = self._as_dict(row.get("parameters_json"))
        return {
            "task_id": row.get("task_id", ""),
            "task_type": row.get("task_type", ""),
            "initiator": row.get("actor", ""),
            "input_objects": self._as_dict(row.get("input_object_json")),
            "model_or_rule_version": row.get("model_or_rule_version", ""),
            "parameters": self._as_dict(params_json.get("parameters", {})),
            "trigger_source": params_json.get("trigger_source", "ui"),
            "model_name": params_json.get("model_name", ""),
            "status": row.get("status", "queued"),
            "started_at": self._ts(row.get("started_at")),
            "ended_at": self._ts(row.get("ended_at")),
            "error_reason": row.get("error_reason", ""),
            "output_summary": self._as_dict(row.get("output_summary_json")),
            "created_at": self._ts(row.get("created_at")),
            # 进度字段从 parameters_json 读回
            "progress_percent": params_json.get("progress_percent", 0),
            "progress_stage": params_json.get("progress_stage", ""),
            "progress_message": params_json.get("progress_message", ""),
        }

    # ---- RegionResultVersion (JSON-only, no DB migration needed) ----

    def put_region_result_version(self, version: Dict[str, Any]) -> None:
        """Save or overwrite a RegionResultVersion by version_id (JSON store only)."""
        state = self._load_json()
        versions: List[Dict[str, Any]] = state.get("region_result_versions", [])
        vid = version.get("version_id", "")
        versions = [v for v in versions if v.get("version_id") != vid]
        versions.insert(0, version)  # newest first
        # Keep at most 50 versions total to prevent unbounded growth
        state["region_result_versions"] = versions[:50]
        self._save_json(state)

    def list_region_result_versions(self, file_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all versions, optionally filtered by file_id. Items list is omitted for performance.

        When file_id is provided, returns versions for that file PLUS any versions with empty
        file_id (e.g. direct_generate versions), so the version bar always includes all methods.
        """
        state = self._load_json()
        versions = state.get("region_result_versions", [])
        if file_id:
            versions = [v for v in versions if v.get("file_id") == file_id or not v.get("file_id")]
        # Strip items array for list view (can be large); caller uses get_region_result_version to load full data
        return [
            {k: v for k, v in ver.items() if k != "items"}
            for ver in versions
        ]

    def get_region_result_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Return the full version including items, or None if not found."""
        state = self._load_json()
        for v in state.get("region_result_versions", []):
            if v.get("version_id") == version_id:
                return v
        return None

    def find_region_version_id_for_candidate(self, candidate_id: str, file_id: Optional[str] = None) -> Optional[str]:
        """Return the snapshot version_id that contains this candidate id in items (newest matching version first)."""
        if not candidate_id:
            return None
        state = self._load_json()
        versions: List[Dict[str, Any]] = list(state.get("region_result_versions", []))
        if file_id:
            versions = [v for v in versions if v.get("file_id") == file_id or not v.get("file_id")]
        for ver in versions:
            for it in ver.get("items") or []:
                if isinstance(it, dict) and it.get("id") == candidate_id:
                    vid = ver.get("version_id")
                    return str(vid) if vid else None
        return None

    def delete_region_result_version(self, version_id: str) -> bool:
        state = self._load_json()
        versions = state.get("region_result_versions", [])
        new_versions = [v for v in versions if v.get("version_id") != version_id]
        if len(new_versions) == len(versions):
            return False
        state["region_result_versions"] = new_versions
        self._save_json(state)
        return True
