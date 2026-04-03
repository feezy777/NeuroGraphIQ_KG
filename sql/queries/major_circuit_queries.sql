-- major_circuit_queries.sql
set search_path to neurokg, public;
select major_circuit_id, circuit_code, en_name, cn_name from major_circuit order by major_circuit_id limit 100;
