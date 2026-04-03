-- sub_region_queries.sql
set search_path to neurokg, public;
select sub_region_id, region_code, en_name, cn_name, parent_major_region_id from sub_brain_region order by sub_region_id limit 100;
