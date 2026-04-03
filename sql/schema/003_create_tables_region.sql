-- 003_create_tables_region.sql
set search_path to neurokg, public;

create table if not exists major_brain_region (
    major_region_id        text primary key,
    organism_id            text references organism(organism_id) on delete set null,
    division_id            text references brain_division(division_id) on delete set null,
    region_code            text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    laterality             text check (laterality in ('left', 'right', 'midline', 'bilateral')),
    region_category        text,
    ontology_source        text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);

create table if not exists sub_brain_region (
    sub_region_id          text primary key,
    organism_id            text references organism(organism_id) on delete set null,
    division_id            text references brain_division(division_id) on delete set null,
    parent_major_region_id text references major_brain_region(major_region_id) on delete set null,
    region_code            text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    laterality             text check (laterality in ('left', 'right', 'midline', 'bilateral')),
    region_category        text,
    ontology_source        text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);

create table if not exists allen_brain_region (
    allen_region_id        text primary key,
    organism_id            text references organism(organism_id) on delete set null,
    division_id            text references brain_division(division_id) on delete set null,
    parent_sub_region_id   text references sub_brain_region(sub_region_id) on delete set null,
    region_code            text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    laterality             text check (laterality in ('left', 'right', 'midline', 'bilateral')),
    region_category        text,
    ontology_source        text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);
