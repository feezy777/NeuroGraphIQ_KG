-- 004_create_tables_connection.sql
set search_path to neurokg, public;

create table if not exists major_connection (
    major_connection_id      text primary key,
    connection_code          text unique,
    en_name                  text,
    cn_name                  text,
    alias                    text[],
    description              text,
    connection_modality      text not null default 'unknown'
                             check (connection_modality in ('structural', 'functional', 'effective', 'unknown')),
    relation_type            text not null default 'indirect_pathway_connection'
                             check (relation_type in ('direct_structural_connection', 'indirect_pathway_connection', 'same_circuit_member')),
    source_major_region_id   text not null references major_brain_region(major_region_id) on delete restrict,
    target_major_region_id   text not null references major_brain_region(major_region_id) on delete restrict,
    confidence               numeric(10,6),
    validation_status        text,
    direction_label          text,
    extraction_method        text,
    data_source              text,
    status                   text,
    remark                   text,
    created_at               timestamp default now(),
    updated_at               timestamp default now(),
    check (source_major_region_id <> target_major_region_id)
);

create table if not exists sub_connection (
    sub_connection_id      text primary key,
    connection_code        text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    connection_modality    text not null default 'unknown'
                           check (connection_modality in ('structural', 'functional', 'effective', 'unknown')),
    source_sub_region_id   text not null references sub_brain_region(sub_region_id) on delete restrict,
    target_sub_region_id   text not null references sub_brain_region(sub_region_id) on delete restrict,
    confidence             numeric(10,6),
    validation_status      text,
    direction_label        text,
    extraction_method      text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now(),
    check (source_sub_region_id <> target_sub_region_id)
);

create table if not exists allen_connection (
    allen_connection_id      text primary key,
    connection_code          text unique,
    en_name                  text,
    cn_name                  text,
    alias                    text[],
    description              text,
    connection_modality      text not null default 'unknown'
                             check (connection_modality in ('structural', 'functional', 'effective', 'unknown')),
    source_allen_region_id   text not null references allen_brain_region(allen_region_id) on delete restrict,
    target_allen_region_id   text not null references allen_brain_region(allen_region_id) on delete restrict,
    confidence               numeric(10,6),
    validation_status        text,
    direction_label          text,
    extraction_method        text,
    data_source              text,
    status                   text,
    remark                   text,
    created_at               timestamp default now(),
    updated_at               timestamp default now(),
    check (source_allen_region_id <> target_allen_region_id)
);
