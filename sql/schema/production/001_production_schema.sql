create schema if not exists neurokg;

create table if not exists neurokg.region_major (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  region_code text not null,
  region_name text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.region_sub (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  region_code text not null,
  region_name text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.region_allen (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  region_code text not null,
  region_name text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.connection (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  source_region text not null,
  target_region text not null,
  directionality text not null default 'unknown',
  confidence numeric(7,4) not null default 0,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.circuit (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  circuit_code text not null,
  circuit_name text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.function_term (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  term_code text not null default '',
  term_name text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.evidence (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  evidence_code text not null default '',
  evidence_text text not null,
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg.cross_granularity_mapping (
  id bigserial primary key,
  source_file_id text not null,
  source_task_id text not null,
  from_layer text not null,
  to_layer text not null,
  mapping_type text not null default '',
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_prod_major_src on neurokg.region_major(source_file_id, source_task_id);
create index if not exists idx_prod_sub_src on neurokg.region_sub(source_file_id, source_task_id);
create index if not exists idx_prod_allen_src on neurokg.region_allen(source_file_id, source_task_id);
create index if not exists idx_prod_conn_src on neurokg.connection(source_file_id, source_task_id);
create index if not exists idx_prod_circuit_src on neurokg.circuit(source_file_id, source_task_id);
