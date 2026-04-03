-- check_consistency.sql
set search_path to neurokg, public;

-- TODO: add full cross-table integrity checks.
select 'organism' as table_name, count(*) as row_count from organism;
