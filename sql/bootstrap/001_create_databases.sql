-- Execute with psql connected to postgres database:
-- psql -h localhost -U postgres -d postgres -f sql/bootstrap/001_create_databases.sql

SELECT 'CREATE DATABASE "NeuroGraphIQ_Workbench"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'NeuroGraphIQ_Workbench')\gexec

SELECT 'CREATE DATABASE "NeuroGraphIQ_KG_Unverified"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'NeuroGraphIQ_KG_Unverified')\gexec

SELECT 'CREATE DATABASE "NeuroGraphIQ_KG"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'NeuroGraphIQ_KG')\gexec
