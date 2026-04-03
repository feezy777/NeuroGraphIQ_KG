-- 007_create_tables_relation.sql
set search_path to neurokg, public;

create table if not exists major_circuit_node (
    major_circuit_id      text not null references major_circuit(major_circuit_id) on delete cascade,
    major_region_id       text not null references major_brain_region(major_region_id) on delete cascade,
    node_order            integer,
    role_label            text,
    created_at            timestamp default now(),
    primary key (major_circuit_id, major_region_id)
);

create table if not exists sub_circuit_node (
    sub_circuit_id        text not null references sub_circuit(sub_circuit_id) on delete cascade,
    sub_region_id         text not null references sub_brain_region(sub_region_id) on delete cascade,
    node_order            integer,
    role_label            text,
    created_at            timestamp default now(),
    primary key (sub_circuit_id, sub_region_id)
);

create table if not exists allen_circuit_node (
    allen_circuit_id      text not null references allen_circuit(allen_circuit_id) on delete cascade,
    allen_region_id       text not null references allen_brain_region(allen_region_id) on delete cascade,
    node_order            integer,
    role_label            text,
    created_at            timestamp default now(),
    primary key (allen_circuit_id, allen_region_id)
);

create table if not exists major_circuit_connection (
    major_circuit_id      text not null references major_circuit(major_circuit_id) on delete cascade,
    major_connection_id   text not null references major_connection(major_connection_id) on delete cascade,
    edge_order            integer,
    created_at            timestamp default now(),
    primary key (major_circuit_id, major_connection_id)
);

create table if not exists sub_circuit_connection (
    sub_circuit_id        text not null references sub_circuit(sub_circuit_id) on delete cascade,
    sub_connection_id     text not null references sub_connection(sub_connection_id) on delete cascade,
    edge_order            integer,
    created_at            timestamp default now(),
    primary key (sub_circuit_id, sub_connection_id)
);

create table if not exists allen_circuit_connection (
    allen_circuit_id      text not null references allen_circuit(allen_circuit_id) on delete cascade,
    allen_connection_id   text not null references allen_connection(allen_connection_id) on delete cascade,
    edge_order            integer,
    created_at            timestamp default now(),
    primary key (allen_circuit_id, allen_connection_id)
);

create table if not exists major_connection_evidence (
    major_connection_id   text not null references major_connection(major_connection_id) on delete cascade,
    evidence_id           text not null references evidence(evidence_id) on delete cascade,
    support_score         numeric(10,6),
    support_note          text,
    created_at            timestamp default now(),
    primary key (major_connection_id, evidence_id)
);

create table if not exists sub_connection_evidence (
    sub_connection_id     text not null references sub_connection(sub_connection_id) on delete cascade,
    evidence_id           text not null references evidence(evidence_id) on delete cascade,
    support_score         numeric(10,6),
    support_note          text,
    created_at            timestamp default now(),
    primary key (sub_connection_id, evidence_id)
);

create table if not exists allen_connection_evidence (
    allen_connection_id   text not null references allen_connection(allen_connection_id) on delete cascade,
    evidence_id           text not null references evidence(evidence_id) on delete cascade,
    support_score         numeric(10,6),
    support_note          text,
    created_at            timestamp default now(),
    primary key (allen_connection_id, evidence_id)
);

create table if not exists major_circuit_evidence (
    major_circuit_id      text not null references major_circuit(major_circuit_id) on delete cascade,
    evidence_id           text not null references evidence(evidence_id) on delete cascade,
    support_score         numeric(10,6),
    support_note          text,
    created_at            timestamp default now(),
    primary key (major_circuit_id, evidence_id)
);

create table if not exists sub_circuit_evidence (
    sub_circuit_id        text not null references sub_circuit(sub_circuit_id) on delete cascade,
    evidence_id           text not null references evidence(evidence_id) on delete cascade,
    support_score         numeric(10,6),
    support_note          text,
    created_at            timestamp default now(),
    primary key (sub_circuit_id, evidence_id)
);

create table if not exists allen_circuit_evidence (
    allen_circuit_id      text not null references allen_circuit(allen_circuit_id) on delete cascade,
    evidence_id           text not null references evidence(evidence_id) on delete cascade,
    support_score         numeric(10,6),
    support_note          text,
    created_at            timestamp default now(),
    primary key (allen_circuit_id, evidence_id)
);
