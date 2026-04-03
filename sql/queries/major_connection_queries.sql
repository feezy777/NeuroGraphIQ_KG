-- major_connection_queries.sql
set search_path to neurokg, public;
select major_connection_id, connection_code, source_major_region_id, target_major_region_id from major_connection order by major_connection_id limit 100;
