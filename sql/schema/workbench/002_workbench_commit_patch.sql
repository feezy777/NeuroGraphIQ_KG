create schema if not exists workbench;

create table if not exists workbench.review_record (
  id text primary key,
  candidate_region_id text not null,
  reviewer text not null default '',
  action text not null,
  before_json jsonb not null default '{}'::jsonb,
  after_json jsonb not null default '{}'::jsonb,
  note text not null default '',
  created_at timestamptz not null
);

alter table workbench.candidate_region
  add column if not exists region_category_candidate text not null default 'brain_region';

alter table workbench.candidate_region
  add column if not exists ontology_source_candidate text not null default 'workbench';

alter table workbench.uploaded_file
  add column if not exists metadata_json jsonb not null default '{}'::jsonb;

alter table workbench.uploaded_file
  add column if not exists tags_json jsonb not null default '[]'::jsonb;

alter table workbench.uploaded_file
  add column if not exists latest_parse_task_id text not null default '';

alter table workbench.uploaded_file
  add column if not exists latest_extract_task_id text not null default '';

alter table workbench.uploaded_file
  add column if not exists latest_commit_task_id text not null default '';

create index if not exists idx_review_record_candidate on workbench.review_record(candidate_region_id, created_at desc);
