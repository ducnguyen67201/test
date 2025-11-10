-- Remove workflow tracking columns from lab_requests table
DROP INDEX IF EXISTS idx_lab_requests_workflow_id;

ALTER TABLE lab_requests
DROP COLUMN IF EXISTS workflow_id,
DROP COLUMN IF EXISTS run_id;
