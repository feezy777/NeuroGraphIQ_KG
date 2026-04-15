create schema if not exists neurokg_unverified;

create table if not exists neurokg_unverified.unverified_region (
  id text primary key,
  source_candidate_region_id text not null unique,
  source_file_id text not null,
  source_parsed_document_id text not null default '',
  granularity text not null,
  en_name text not null default '',
  cn_name text not null default '',
  alias text not null default '',
  description text not null default '',
  laterality text not null default '',
  region_category text not null default 'brain_region',
  parent_region_ref text not null default '',
  ontology_source text not null default 'workbench',
  data_source text not null default '',
  confidence numeric(7,4) not null default 0,
  validation_status text not null default 'validation_pending',
  promotion_status text not null default 'not_ready',
  review_status text not null default 'reviewed',
  review_note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists neurokg_unverified.unverified_region_validation (
  id text primary key,
  unverified_region_id text not null,
  validation_type text not null default 'rule',
  validator_name text not null default '',
  status text not null,
  score numeric(7,4) not null default 0,
  message text not null default '',
  detail_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists neurokg_unverified.promotion_record (
  id text primary key,
  unverified_region_id text not null,
  target_table text not null default '',
  target_region_id text not null default '',
  region_code text not null default '',
  status text not null,
  message text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists idx_unverified_region_file on neurokg_unverified.unverified_region(source_file_id, created_at desc);
create index if not exists idx_unverified_region_status on neurokg_unverified.unverified_region(validation_status, promotion_status);
create index if not exists idx_unverified_region_validation_ref on neurokg_unverified.unverified_region_validation(unverified_region_id, created_at desc);
create index if not exists idx_promotion_record_ref on neurokg_unverified.promotion_record(unverified_region_id, created_at desc);
