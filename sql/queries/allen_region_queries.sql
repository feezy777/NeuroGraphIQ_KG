-- allen_region_queries.sql
set search_path to neurokg, public;
select allen_region_id, region_code, en_name, cn_name, parent_sub_region_id from allen_brain_region order by allen_region_id limit 100;
