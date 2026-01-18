-- Migration: Add missing fields to information_units table
-- Date: 2026-01-19
-- Description: Adds 10 missing critical fields for 4D scoring, HEX classification, and entity hierarchy
--              Also adds entity_processed flag to prevent infinite loop in EntityBackfill

-- Add event_time, report_time, and time_sensitivity
ALTER TABLE information_units ADD COLUMN event_time TEXT;
ALTER TABLE information_units ADD COLUMN report_time TIMESTAMP;
ALTER TABLE information_units ADD COLUMN time_sensitivity TEXT DEFAULT 'normal';

-- Add 4D value scoring fields
ALTER TABLE information_units ADD COLUMN information_gain REAL DEFAULT 5.0;
ALTER TABLE information_units ADD COLUMN actionability REAL DEFAULT 5.0;
ALTER TABLE information_units ADD COLUMN scarcity REAL DEFAULT 5.0;
ALTER TABLE information_units ADD COLUMN impact_magnitude REAL DEFAULT 5.0;

-- Add HEX state classification
ALTER TABLE information_units ADD COLUMN state_change_type TEXT;
ALTER TABLE information_units ADD COLUMN state_change_subtypes TEXT;  -- JSON array

-- Add three-level entity hierarchy
ALTER TABLE information_units ADD COLUMN entity_hierarchy TEXT;  -- JSON array of EntityAnchor

-- Add extracted entities and relations for knowledge graph
ALTER TABLE information_units ADD COLUMN extracted_entities TEXT;  -- JSON array
ALTER TABLE information_units ADD COLUMN extracted_relations TEXT;  -- JSON array

-- Add entity_processed flag to prevent infinite loop in EntityBackfill
ALTER TABLE information_units ADD COLUMN entity_processed BOOLEAN DEFAULT FALSE;

-- Add new indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_info_state_type ON information_units(state_change_type);
CREATE INDEX IF NOT EXISTS idx_info_value ON information_units(information_gain, actionability, scarcity, impact_magnitude);
CREATE INDEX IF NOT EXISTS idx_info_entity_processed ON information_units(entity_processed);
