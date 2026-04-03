-- 005_create_tables_circuit.sql
set search_path to neurokg, public;

create table if not exists major_circuit (
    major_circuit_id            text primary key,
    circuit_code                text unique,
    en_name                     text,
    cn_name                     text,
    alias                       text[],
    description                 text,
    circuit_kind                text not null default 'unknown'
                                check (circuit_kind in ('structural', 'functional', 'inferred', 'unknown')),
    loop_type                   text check (loop_type in ('strict', 'inferred', 'functional')),
    cycle_verified              boolean,
    confidence_circuit          numeric(10,6),
    validation_status_circuit   text,
    node_count                  integer,
    connection_count            integer,
    data_source                 text,
    status                      text,
    remark                      text,
    created_at                  timestamp default now(),
    updated_at                  timestamp default now()
);

create table if not exists sub_circuit (
    sub_circuit_id              text primary key,
    circuit_code                text unique,
    en_name                     text,
    cn_name                     text,
    alias                       text[],
    description                 text,
    circuit_kind                text not null default 'unknown'
                                check (circuit_kind in ('structural', 'functional', 'inferred', 'unknown')),
    loop_type                   text check (loop_type in ('strict', 'inferred', 'functional')),
    cycle_verified              boolean,
    confidence_circuit          numeric(10,6),
    validation_status_circuit   text,
    node_count                  integer,
    connection_count            integer,
    data_source                 text,
    status                      text,
    remark                      text,
    created_at                  timestamp default now(),
    updated_at                  timestamp default now()
);

create table if not exists allen_circuit (
    allen_circuit_id            text primary key,
    circuit_code                text unique,
    en_name                     text,
    cn_name                     text,
    alias                       text[],
    description                 text,
    circuit_kind                text not null default 'unknown'
                                check (circuit_kind in ('structural', 'functional', 'inferred', 'unknown')),
    loop_type                   text check (loop_type in ('strict', 'inferred', 'functional')),
    cycle_verified              boolean,
    confidence_circuit          numeric(10,6),
    validation_status_circuit   text,
    node_count                  integer,
    connection_count            integer,
    data_source                 text,
    status                      text,
    remark                      text,
    created_at                  timestamp default now(),
    updated_at                  timestamp default now()
);
