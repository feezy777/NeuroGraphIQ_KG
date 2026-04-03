-- 006_create_tables_evidence.sql
set search_path to neurokg, public;

create table if not exists evidence (
    evidence_id             text primary key,
    evidence_code           text unique,
    en_name                 text,
    cn_name                 text,
    alias                   text[],
    description             text,
    evidence_text           text,
    source_title            text,
    pmid                    text,
    doi                     text,
    section                 text,
    publication_year        integer,
    journal                 text,
    evidence_type           text check (evidence_type in ('paper', 'abstract', 'database_record', 'review', 'manual_note')),
    data_source             text,
    status                  text,
    remark                  text,
    created_at              timestamp default now(),
    updated_at              timestamp default now()
);
