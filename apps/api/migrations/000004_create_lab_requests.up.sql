-- Create lab_requests table for Request Lab feature
-- This table stores user requests for CVE analysis labs with guardrails

-- Create ENUM types for lab_requests
CREATE TYPE lab_source AS ENUM ('quick_pick', 'manual');
CREATE TYPE lab_severity AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE lab_status AS ENUM ('draft', 'pending_guardrail', 'rejected', 'queued', 'running', 'completed', 'expired');

-- Create lab_requests table
CREATE TABLE IF NOT EXISTS lab_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source lab_source NOT NULL,
    cve_id VARCHAR(50),
    title VARCHAR(500) NOT NULL,
    severity lab_severity NOT NULL,
    description TEXT,
    objective TEXT,
    ttl_hours INTEGER NOT NULL DEFAULT 4 CHECK (ttl_hours > 0 AND ttl_hours <= 8),
    expires_at TIMESTAMP,
    status lab_status NOT NULL DEFAULT 'draft',
    blueprint JSONB,
    guardrail_snapshot JSONB,
    risk_rating JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_lab_requests_user_id ON lab_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_lab_requests_status ON lab_requests(status);
CREATE INDEX IF NOT EXISTS idx_lab_requests_expires_at ON lab_requests(expires_at);
CREATE INDEX IF NOT EXISTS idx_lab_requests_user_status ON lab_requests(user_id, status);
CREATE INDEX IF NOT EXISTS idx_lab_requests_created_at ON lab_requests(created_at DESC);

-- Add role field to users table for TTL override permissions
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'user';
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Create materialized view for recent CVEs (quick picks)
-- For MVP, we'll populate this with seed data
CREATE TABLE IF NOT EXISTS recent_cves (
    id VARCHAR(50) PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    severity lab_severity NOT NULL,
    published_at TIMESTAMP NOT NULL,
    exploitability_score DECIMAL(3,1) CHECK (exploitability_score >= 0 AND exploitability_score <= 10),
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recent_cves_published_at ON recent_cves(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_recent_cves_severity ON recent_cves(severity);

-- Seed recent CVEs for quick picks (MVP data)
INSERT INTO recent_cves (id, title, severity, published_at, exploitability_score, description) VALUES
('CVE-2024-1234', 'Remote Code Execution in Apache Struts', 'critical', NOW() - INTERVAL '2 days', 9.8, 'A critical vulnerability allowing remote code execution in Apache Struts 2.x through specially crafted OGNL expressions.'),
('CVE-2024-5678', 'SQL Injection in WordPress Plugin', 'high', NOW() - INTERVAL '5 days', 8.5, 'SQL injection vulnerability in popular WordPress contact form plugin affecting versions prior to 5.2.1.'),
('CVE-2024-9012', 'Cross-Site Scripting in React Admin Dashboard', 'medium', NOW() - INTERVAL '7 days', 6.1, 'Stored XSS vulnerability in React-based admin dashboard through unsanitized user input.'),
('CVE-2024-3456', 'Authentication Bypass in Spring Boot', 'critical', NOW() - INTERVAL '10 days', 9.1, 'Authentication bypass in Spring Boot Security allowing unauthorized access to protected endpoints.'),
('CVE-2024-7890', 'Path Traversal in Node.js Express', 'high', NOW() - INTERVAL '12 days', 7.5, 'Directory traversal vulnerability in Express.js static file serving middleware.'),
('CVE-2024-2468', 'Privilege Escalation in Docker', 'high', NOW() - INTERVAL '15 days', 8.8, 'Container escape vulnerability in Docker runtime allowing privilege escalation to host.'),
('CVE-2024-1357', 'Denial of Service in Nginx', 'medium', NOW() - INTERVAL '18 days', 5.3, 'DoS vulnerability in Nginx HTTP/2 implementation causing server crashes with malformed requests.'),
('CVE-2024-8024', 'SSRF in Python Flask', 'medium', NOW() - INTERVAL '20 days', 6.5, 'Server-Side Request Forgery in Flask applications using vulnerable URL parsing library.'),
('CVE-2024-4680', 'Buffer Overflow in OpenSSL', 'critical', NOW() - INTERVAL '25 days', 9.8, 'Memory corruption vulnerability in OpenSSL 3.x allowing remote code execution.'),
('CVE-2024-9753', 'CSRF in Django Admin', 'low', NOW() - INTERVAL '30 days', 4.3, 'Cross-Site Request Forgery in Django admin panel affecting specific configurations.')
ON CONFLICT (id) DO NOTHING;

-- Add table comments for documentation
COMMENT ON TABLE lab_requests IS 'User requests for CVE analysis labs with guardrail enforcement';
COMMENT ON COLUMN lab_requests.source IS 'How the lab was initiated: quick_pick (from CVE list) or manual (user input)';
COMMENT ON COLUMN lab_requests.cve_id IS 'CVE identifier if applicable (e.g., CVE-2024-1234)';
COMMENT ON COLUMN lab_requests.ttl_hours IS 'Time-to-live in hours (default 4, max 8, >4 requires admin role)';
COMMENT ON COLUMN lab_requests.expires_at IS 'Calculated expiration timestamp based on TTL';
COMMENT ON COLUMN lab_requests.blueprint IS 'JSON structure containing lab setup instructions generated by LLM';
COMMENT ON COLUMN lab_requests.guardrail_snapshot IS 'JSON record of guardrail checks performed at confirmation time';
COMMENT ON COLUMN lab_requests.risk_rating IS 'JSON containing risk assessment and justification';

COMMENT ON TABLE recent_cves IS 'Recent CVE entries for quick pick selection in Request Lab';
COMMENT ON COLUMN recent_cves.exploitability_score IS 'CVSS exploitability score (0-10)';
