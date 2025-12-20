-- Add workflow tracking columns to lab_requests table
ALTER TABLE lab_requests
ADD COLUMN workflow_id VARCHAR(255),
ADD COLUMN run_id VARCHAR(255);

-- Create index for workflow_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_lab_requests_workflow_id ON lab_requests(workflow_id);

-- Add comment for documentation
COMMENT ON COLUMN lab_requests.workflow_id IS 'Temporal workflow ID for tracking lab provisioning';
COMMENT ON COLUMN lab_requests.run_id IS 'Temporal run ID for the workflow execution';
