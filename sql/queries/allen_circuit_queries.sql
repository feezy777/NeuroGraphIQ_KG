-- allen_circuit_queries.sql
set search_path to neurokg, public;
select allen_circuit_id, circuit_code, en_name, cn_name from allen_circuit order by allen_circuit_id limit 100;
