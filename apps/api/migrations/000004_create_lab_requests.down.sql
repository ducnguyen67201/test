-- Rollback lab_requests table and related structures

-- Drop indexes first
DROP INDEX IF EXISTS idx_recent_cves_severity;
DROP INDEX IF EXISTS idx_recent_cves_published_at;
DROP INDEX IF EXISTS idx_users_role;
DROP INDEX IF EXISTS idx_lab_requests_created_at;
DROP INDEX IF EXISTS idx_lab_requests_user_status;
DROP INDEX IF EXISTS idx_lab_requests_expires_at;
DROP INDEX IF EXISTS idx_lab_requests_status;
DROP INDEX IF EXISTS idx_lab_requests_user_id;

-- Remove role column from users table
ALTER TABLE users DROP COLUMN IF EXISTS role;

-- Drop tables (order matters due to foreign keys)
DROP TABLE IF EXISTS recent_cves;
DROP TABLE IF EXISTS lab_requests;

-- Drop ENUM types
DROP TYPE IF EXISTS lab_status;
DROP TYPE IF EXISTS lab_severity;
DROP TYPE IF EXISTS lab_source;
