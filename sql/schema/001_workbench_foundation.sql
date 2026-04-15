-- Stage-1 schema skeleton for future database implementation.
-- This file is not executed by the phase-1 JSON repository runtime.

create schema if not exists neurokg_stage;
create schema if not exists neurokg_prod;

create table if not exists neurokg_stage.file_record (
  file_id text primary key,
  filename text not null,
  file_type text not null,
  file_size bigint not null,
  source text not null,
  status text not null,
  version integer not null default 1,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create table if not exists neurokg_stage.parsed_document (
  id bigserial primary key,
  file_id text not null,
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
  created_at timestamptz not null
);

create table if not exists neurokg_stage.content_chunk (
  id bigserial primary key,
  chunk_id text not null,
  file_id text not null,
  chunk_type text not null,
  chunk_text text,
  source_location_json jsonb not null default '{}'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_stage.candidate_entity (
  id bigserial primary key,
  entity_id text not null,
  file_id text not null,
  entity_type text not null,
  name text not null,
  confidence numeric(5,4),
  source_chunk_ids jsonb not null default '[]'::jsonb,
  attributes_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_stage.candidate_relation (
  id bigserial primary key,
  relation_id text not null,
  file_id text not null,
  source_entity_id text not null,
  target_entity_id text not null,
  relation_type text not null,
  confidence numeric(5,4),
  source_chunk_ids jsonb not null default '[]'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_stage.candidate_connection (
  id bigserial primary key,
  connection_id text not null,
  file_id text not null,
  source_region text not null,
  target_region text not null,
  directionality text,
  confidence numeric(5,4),
  evidence_chunk_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_stage.candidate_circuit (
  id bigserial primary key,
  circuit_id text not null,
  file_id text not null,
  circuit_name text not null,
  nodes jsonb not null default '[]'::jsonb,
  circuit_family text,
  confidence numeric(5,4),
  evidence_chunk_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_stage.task_run (
  task_id text primary key,
  task_type text not null,
  status text not null,
  actor text not null,
  input_object text not null,
  model_or_rule_version text not null,
  parameters_json jsonb not null,
  output_summary_json jsonb not null,
  started_at timestamptz not null,
  ended_at timestamptz
);

create table if not exists neurokg_stage.task_log (
  id bigserial primary key,
  task_id text not null,
  level text not null,
  message text not null,
  created_at timestamptz not null
);

create table if not exists neurokg_stage.validation_run (
  validation_run_id text primary key,
  file_id text not null,
  structure_result_json jsonb not null,
  ontology_result_json jsonb not null,
  model_result_json jsonb not null,
  review_result_json jsonb not null,
  created_at timestamptz not null
);

create table if not exists neurokg_stage.granularity_mapping (
  mapping_id text primary key,
  file_id text not null,
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

create table if not exists neurokg_stage.model_config (
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
