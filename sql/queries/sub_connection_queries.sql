-- sub_connection_queries.sql
set search_path to neurokg, public;
select sub_connection_id, connection_code, source_sub_region_id, target_sub_region_id from sub_connection order by sub_connection_id limit 100;
