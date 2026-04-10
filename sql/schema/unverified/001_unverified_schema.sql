create schema if not exists neurokg_unverified;

create table if not exists neurokg_unverified.unverified_file_runs (
  run_id bigserial primary key,
  file_id text not null,
  task_id text not null,
  normalize_mode text not null,
  validate_mode text not null,
  overall_label text not null,
  overall_score numeric(7,4) not null default 0,
  overall_reason text not null default '',
  trace_id text not null default '',
  request_sent boolean not null default false,
  response_received boolean not null default false,
  http_status integer not null default 0,
  elapsed_ms integer not null default 0,
  config_source text not null default 'global',
  status text not null default 'stored',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (file_id, task_id)
);

create table if not exists neurokg_unverified.unverified_file_payloads (
  id bigserial primary key,
  run_id bigint not null references neurokg_unverified.unverified_file_runs(run_id) on delete cascade,
  file_id text not null,
  task_id text not null,
  normalized_json jsonb not null default '{}'::jsonb,
  validation_report_json jsonb not null default '{}'::jsonb,
  granularity_mapping_json jsonb not null default '{}'::jsonb,
  candidate_payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_unverified.unverified_review_state (
  id bigserial primary key,
  run_id bigint not null references neurokg_unverified.unverified_file_runs(run_id) on delete cascade,
  review_status text not null default 'pending',
  reviewer text not null default '',
  review_note text not null default '',
  reviewed_at timestamptz
);

create or replace view neurokg_unverified.v_latest_unverified_by_file as
select distinct on (file_id)
  run_id,
  file_id,
  task_id,
  normalize_mode,
  validate_mode,
  overall_label,
  overall_score,
  status,
  created_at
from neurokg_unverified.unverified_file_runs
order by file_id, created_at desc;

create index if not exists idx_unverified_file_runs_file on neurokg_unverified.unverified_file_runs(file_id);
create index if not exists idx_unverified_file_runs_task on neurokg_unverified.unverified_file_runs(task_id);
create index if not exists idx_unverified_file_runs_created on neurokg_unverified.unverified_file_runs(created_at desc);
