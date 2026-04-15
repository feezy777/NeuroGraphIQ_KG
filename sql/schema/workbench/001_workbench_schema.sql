create schema if not exists workbench;

create table if not exists workbench.file_record (
  file_id text primary key,
  filename text not null,
  file_type text not null,
  mime_type text not null default '',
  status text not null,
  version integer not null default 1,
  source text not null default 'upload',
  size_bytes bigint not null default 0,
  checksum text not null default '',
  path text not null default '',
  tags_json jsonb not null default '[]'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  latest_parse_task_id text not null default '',
  latest_extract_task_id text not null default '',
  latest_validate_task_id text not null default '',
  latest_map_task_id text not null default '',
  latest_ingest_task_id text not null default '',
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique (filename, version)
);

create table if not exists workbench.file_blob (
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  version integer not null,
  content_bytea bytea not null,
  encoding text not null default 'binary',
  is_compressed boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (file_id, version)
);

create table if not exists workbench.file_revision (
  revision_id text primary key,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  version integer not null,
  revision_note text not null default '',
  created_at timestamptz not null
);

create table if not exists workbench.parsed_document (
  id bigserial primary key,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  title text,
  file_type text,
  source text,
  authors_json jsonb not null default '[]'::jsonb,
  year integer,
  doi text,
  page_range text,
  parser_name text,
  parser_version text,
  document_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null,
  unique(file_id)
);

create table if not exists workbench.content_chunk (
  id bigserial primary key,
  chunk_id text not null,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  chunk_type text not null,
  chunk_text text,
  source_location_json jsonb not null default '{}'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (chunk_id)
);

create table if not exists workbench.candidate_entity (
  id bigserial primary key,
  entity_id text not null,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  entity_type text not null,
  name text not null,
  confidence numeric(5,4),
  source_chunk_ids jsonb not null default '[]'::jsonb,
  attributes_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (entity_id)
);

create table if not exists workbench.candidate_relation (
  id bigserial primary key,
  relation_id text not null,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  source_entity_id text not null,
  target_entity_id text not null,
  relation_type text not null,
  confidence numeric(5,4),
  source_chunk_ids jsonb not null default '[]'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (relation_id)
);

create table if not exists workbench.candidate_connection (
  id bigserial primary key,
  connection_id text not null,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  source_region text not null,
  target_region text not null,
  directionality text,
  confidence numeric(5,4),
  evidence_chunk_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (connection_id)
);

create table if not exists workbench.candidate_circuit (
  id bigserial primary key,
  circuit_id text not null,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  circuit_name text not null,
  nodes jsonb not null default '[]'::jsonb,
  circuit_family text,
  confidence numeric(5,4),
  evidence_chunk_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (circuit_id)
);

create table if not exists workbench.validation_run (
  validation_run_id text primary key,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  task_id text not null,
  structure_result_json jsonb not null default '{}'::jsonb,
  ontology_result_json jsonb not null default '{}'::jsonb,
  model_result_json jsonb not null default '{}'::jsonb,
  review_result_json jsonb not null default '{}'::jsonb,
  overall_label text not null default 'UNKNOWN',
  overall_score numeric(7,4) not null default 0,
  created_at timestamptz not null
);

create table if not exists workbench.granularity_mapping (
  mapping_id text primary key,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  major_regions_json jsonb not null default '[]'::jsonb,
  sub_regions_json jsonb not null default '[]'::jsonb,
  allen_regions_json jsonb not null default '[]'::jsonb,
  connections_json jsonb not null default '[]'::jsonb,
  circuits_json jsonb not null default '[]'::jsonb,
  functions_json jsonb not null default '[]'::jsonb,
  evidences_json jsonb not null default '[]'::jsonb,
  cross_mapping_json jsonb not null default '[]'::jsonb,
  created_at timestamptz not null
);

create table if not exists workbench.task_run (
  task_id text primary key,
  task_type text not null,
  status text not null,
  actor text not null,
  input_object_json jsonb not null default '{}'::jsonb,
  model_or_rule_version text not null default '',
  parameters_json jsonb not null default '{}'::jsonb,
  output_summary_json jsonb not null default '{}'::jsonb,
  error_reason text not null default '',
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists workbench.task_log (
  id bigserial primary key,
  log_id text not null,
  task_id text not null,
  module text not null,
  level text not null,
  message text not null,
  created_at timestamptz not null
);

create table if not exists workbench.model_config (
  config_id text primary key,
  deepseek_enabled boolean not null default false,
  deepseek_api_key text,
  deepseek_base_url text,
  deepseek_model text,
  routing_policy text,
  param_version text,
  task_override_json jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null
);

create table if not exists workbench.task_config_override (
  override_id text primary key,
  task_id text not null,
  normalize_mode text,
  validate_mode text,
  override_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null
);

create table if not exists workbench.workspace_snapshot (
  snapshot_id text primary key,
  payload_json jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null
);

create table if not exists workbench.ingestion_run (
  run_id text primary key,
  file_id text not null references workbench.file_record(file_id) on delete cascade,
  task_id text not null,
  target_db text not null,
  target_schema text not null,
  result_status text not null,
  summary_json jsonb not null default '{}'::jsonb,
  error_reason text not null default '',
  created_at timestamptz not null
);

create index if not exists idx_workbench_file_status on workbench.file_record(status);
create index if not exists idx_workbench_chunk_file on workbench.content_chunk(file_id);
create index if not exists idx_workbench_entity_file on workbench.candidate_entity(file_id);
create index if not exists idx_workbench_relation_file on workbench.candidate_relation(file_id);
create index if not exists idx_workbench_connection_file on workbench.candidate_connection(file_id);
create index if not exists idx_workbench_circuit_file on workbench.candidate_circuit(file_id);
create index if not exists idx_workbench_task_created on workbench.task_run(created_at desc);
create index if not exists idx_workbench_task_log_task on workbench.task_log(task_id, created_at);

-- stage-2 brain-region flow tables (kept alongside existing skeleton tables)
create table if not exists workbench.uploaded_file (
  id text primary key,
  file_name text not null,
  file_type text not null,
  mime_type text not null default '',
  storage_path text not null default '',
  content_ref text not null default '',
  size_bytes bigint not null default 0,
  upload_status text not null default 'uploaded',
  source text not null default 'upload',
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deleted_at timestamptz
);

create table if not exists workbench.extraction_run (
  id text primary key,
  file_id text not null,
  task_type text not null,
  trigger_source text not null default 'ui',
  model_name text not null default '',
  params_json jsonb not null default '{}'::jsonb,
  status text not null,
  started_at timestamptz,
  finished_at timestamptz,
  summary text not null default '',
  error_message text not null default ''
);

create table if not exists workbench.task_log_v2 (
  id text primary key,
  run_id text not null,
  level text not null,
  event_type text not null,
  message text not null,
  detail_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null
);

create table if not exists workbench.candidate_region (
  id text primary key,
  file_id text not null,
  parsed_document_id text not null default '',
  chunk_id text not null default '',
  source_text text not null default '',
  en_name_candidate text not null default '',
  cn_name_candidate text not null default '',
  alias_candidates jsonb not null default '[]'::jsonb,
  laterality_candidate text not null default 'unknown',
  granularity_candidate text not null default 'unknown',
  parent_region_candidate text not null default '',
  confidence numeric(7,4) not null default 0,
  extraction_method text not null default 'local_rule',
  llm_model text not null default '',
  status text not null default 'pending_review',
  review_note text not null default '',
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create index if not exists idx_uploaded_file_status on workbench.uploaded_file(upload_status);
create index if not exists idx_extraction_run_file on workbench.extraction_run(file_id, started_at desc);
create index if not exists idx_task_log_v2_run on workbench.task_log_v2(run_id, created_at);
create index if not exists idx_candidate_region_file on workbench.candidate_region(file_id, status);
