-- major_region_queries.sql
set search_path to neurokg, public;
select major_region_id, region_code, en_name, cn_name from major_brain_region order by major_region_id limit 100;
