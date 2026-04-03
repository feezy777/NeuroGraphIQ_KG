-- 002_seed_reference_data.sql
set search_path to neurokg, public;

insert into anatomical_system (
    system_id, organism_id, system_code, en_name, cn_name, data_source, status
)
values (
    'SYS_NERVOUS',
    'ORG_HUMAN',
    'SYS_NERVOUS',
    'Nervous System',
    'nervous_system',
    'seed_reference',
    'active'
)
on conflict (system_id) do update set
    organism_id = excluded.organism_id,
    system_code = excluded.system_code,
    en_name = excluded.en_name,
    cn_name = excluded.cn_name,
    data_source = excluded.data_source,
    status = excluded.status;

insert into organ (
    organ_id, system_id, organ_code, en_name, cn_name, data_source, status
)
values (
    'ORGN_HUMAN_BRAIN',
    'SYS_NERVOUS',
    'ORGN_HUMAN_BRAIN',
    'Human Brain',
    'human_brain',
    'seed_reference',
    'active'
)
on conflict (organ_id) do update set
    system_id = excluded.system_id,
    organ_code = excluded.organ_code,
    en_name = excluded.en_name,
    cn_name = excluded.cn_name,
    data_source = excluded.data_source,
    status = excluded.status;

insert into brain_division (
    division_id, organ_id, division_code, en_name, cn_name, division_type, data_source, status
)
values (
    'DIV_NON_LOBE_DIVISION_BRAIN',
    'ORGN_HUMAN_BRAIN',
    'DIV_NON_LOBE_DIVISION_BRAIN',
    'Brain (Non-lobe)',
    'brain_non_lobe',
    'non_lobe_division',
    'seed_reference',
    'active'
)
on conflict (division_id) do update set
    organ_id = excluded.organ_id,
    division_code = excluded.division_code,
    en_name = excluded.en_name,
    cn_name = excluded.cn_name,
    division_type = excluded.division_type,
    data_source = excluded.data_source,
    status = excluded.status;
