-- Runs once, when the volume is first created.
CREATE SCHEMA IF NOT EXISTS langgraph AUTHORIZATION crm;
CREATE DATABASE crm_test OWNER crm;
\connect crm_test
CREATE SCHEMA IF NOT EXISTS langgraph AUTHORIZATION crm;
