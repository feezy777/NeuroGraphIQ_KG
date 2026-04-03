-- allen_connection_queries.sql
set search_path to neurokg, public;
select allen_connection_id, connection_code, source_allen_region_id, target_allen_region_id from allen_connection order by allen_connection_id limit 100;
