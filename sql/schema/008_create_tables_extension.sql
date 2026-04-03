-- 008_create_tables_extension.sql
set search_path to neurokg, public;

create table if not exists allen_brain_region_ext (
    allen_region_id       text primary key references allen_brain_region(allen_region_id) on delete cascade,
    allen_atlas_id        text,
    allen_parent_code     text,
    allen_tree_path       text,
    allen_acronym         text,
    extra_json            jsonb
);

create table if not exists major_connection_structural_ext (
    major_connection_id   text primary key references major_connection(major_connection_id) on delete cascade,
    tract_strength        numeric(12,6),
    tract_count           integer,
    measurement_method    text,
    hemisphere_note       text,
    extra_json            jsonb
);

create table if not exists sub_connection_structural_ext (
    sub_connection_id     text primary key references sub_connection(sub_connection_id) on delete cascade,
    tract_strength        numeric(12,6),
    tract_count           integer,
    measurement_method    text,
    hemisphere_note       text,
    extra_json            jsonb
);

create table if not exists allen_connection_structural_ext (
    allen_connection_id   text primary key references allen_connection(allen_connection_id) on delete cascade,
    tract_strength        numeric(12,6),
    tract_count           integer,
    measurement_method    text,
    hemisphere_note       text,
    extra_json            jsonb
);

create table if not exists major_connection_functional_ext (
    major_connection_id   text primary key references major_connection(major_connection_id) on delete cascade,
    correlation_value     numeric(12,6),
    fisher_z              numeric(12,6),
    p_value               numeric(12,6),
    sample_size           integer,
    condition_label       text,
    time_window           text,
    preprocessing_note    text,
    extra_json            jsonb
);

create table if not exists sub_connection_functional_ext (
    sub_connection_id     text primary key references sub_connection(sub_connection_id) on delete cascade,
    correlation_value     numeric(12,6),
    fisher_z              numeric(12,6),
    p_value               numeric(12,6),
    sample_size           integer,
    condition_label       text,
    time_window           text,
    preprocessing_note    text,
    extra_json            jsonb
);

create table if not exists allen_connection_functional_ext (
    allen_connection_id   text primary key references allen_connection(allen_connection_id) on delete cascade,
    correlation_value     numeric(12,6),
    fisher_z              numeric(12,6),
    p_value               numeric(12,6),
    sample_size           integer,
    condition_label       text,
    time_window           text,
    preprocessing_note    text,
    extra_json            jsonb
);

create table if not exists major_circuit_functional_ext (
    major_circuit_id      text primary key references major_circuit(major_circuit_id) on delete cascade,
    activation_pattern    text,
    condition_label       text,
    support_metric        text,
    extra_json            jsonb
);

create table if not exists sub_circuit_functional_ext (
    sub_circuit_id        text primary key references sub_circuit(sub_circuit_id) on delete cascade,
    activation_pattern    text,
    condition_label       text,
    support_metric        text,
    extra_json            jsonb
);

create table if not exists allen_circuit_functional_ext (
    allen_circuit_id      text primary key references allen_circuit(allen_circuit_id) on delete cascade,
    activation_pattern    text,
    condition_label       text,
    support_metric        text,
    extra_json            jsonb
);
