-- sub_circuit_queries.sql
set search_path to neurokg, public;
select sub_circuit_id, circuit_code, en_name, cn_name from sub_circuit order by sub_circuit_id limit 100;
