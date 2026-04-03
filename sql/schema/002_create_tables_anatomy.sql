-- 002_create_tables_anatomy.sql
set search_path to neurokg, public;

create table if not exists organism (
    organism_id            text primary key,
    organism_code          text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    species                text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);

create table if not exists anatomical_system (
    system_id              text primary key,
    organism_id            text references organism(organism_id) on delete set null,
    system_code            text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);

create table if not exists organ (
    organ_id               text primary key,
    system_id              text references anatomical_system(system_id) on delete set null,
    organ_code             text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);

create table if not exists brain_division (
    division_id            text primary key,
    organ_id               text references organ(organ_id) on delete set null,
    division_code          text unique,
    en_name                text,
    cn_name                text,
    alias                  text[],
    description            text,
    division_type          text not null check (division_type in ('brain_lobe', 'non_lobe_division')),
    data_source            text,
    status                 text,
    remark                 text,
    created_at             timestamp default now(),
    updated_at             timestamp default now()
);
