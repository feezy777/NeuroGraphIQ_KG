-- 001_seed_test_data.sql
set search_path to neurokg, public;

-- Minimal smoke seed using semantic IDs (safe to edit)
insert into organism (
    organism_id, organism_code, en_name, cn_name, species, data_source, status
)
values (
    'ORG_HUMAN',
    'ORG_HUMAN',
    'Human',
    'human',
    'Homo sapiens',
    'seed_test',
    'active'
)
on conflict (organism_id) do update set
    organism_code = excluded.organism_code,
    en_name = excluded.en_name,
    cn_name = excluded.cn_name,
    species = excluded.species,
    data_source = excluded.data_source,
    status = excluded.status;
