-- 001_create_schema.sql
-- Create namespace for NeuroKG split-table model.

create schema if not exists neurokg;
set search_path to neurokg, public;
