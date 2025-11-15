-- Create recipes table for reusable environment templates
-- Recipes are templates with software requirements pulled from internet (CVE data, package versions, etc.)

-- Create recipes table
CREATE TABLE IF NOT EXISTS recipes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id UUID REFERENCES intents(id) ON DELETE SET NULL,
    name VARCHAR(500) NOT NULL,
    description TEXT,
    software VARCHAR(200) NOT NULL,
    version_constraint VARCHAR(100),
    os VARCHAR(100) NOT NULL DEFAULT 'ubuntu2204',
    packages JSONB NOT NULL DEFAULT '[]'::jsonb,
    network_requirements TEXT,
    compliance_controls JSONB DEFAULT '[]'::jsonb,
    validation_checks JSONB DEFAULT '[]'::jsonb,
    cve_data JSONB,
    source_urls JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_recipes_software ON recipes(software);
CREATE INDEX IF NOT EXISTS idx_recipes_os ON recipes(os);
CREATE INDEX IF NOT EXISTS idx_recipes_is_active ON recipes(is_active);
CREATE INDEX IF NOT EXISTS idx_recipes_created_by ON recipes(created_by);
CREATE INDEX IF NOT EXISTS idx_recipes_created_at ON recipes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recipes_intent_id ON recipes(intent_id);

-- Create GIN indexes for JSONB queries
CREATE INDEX IF NOT EXISTS idx_recipes_packages_gin ON recipes USING GIN (packages);
CREATE INDEX IF NOT EXISTS idx_recipes_cve_data_gin ON recipes USING GIN (cve_data);
CREATE INDEX IF NOT EXISTS idx_recipes_compliance_gin ON recipes USING GIN (compliance_controls);

-- Add table comments for documentation
COMMENT ON TABLE recipes IS 'Reusable environment templates with software requirements from CVE databases and package registries';
COMMENT ON COLUMN recipes.intent_id IS 'Optional foreign key to intent that generated this recipe';
COMMENT ON COLUMN recipes.name IS 'Recipe name (e.g., "Apache CVE-2019-0234 Regression Rig")';
COMMENT ON COLUMN recipes.description IS 'Human-readable description of the recipe purpose';
COMMENT ON COLUMN recipes.software IS 'Primary software stack (e.g., "apache-httpd", "node", "jquery")';
COMMENT ON COLUMN recipes.version_constraint IS 'Version constraint (semver or OS label, e.g., "2.4.49", ">=16.0.0")';
COMMENT ON COLUMN recipes.os IS 'Operating system base image (e.g., "ubuntu2204", "debian12")';
COMMENT ON COLUMN recipes.packages IS 'JSON array of package objects: [{name, version, source}]';
COMMENT ON COLUMN recipes.network_requirements IS 'Network configuration requirements (e.g., "isolated vlan, outbound disabled")';
COMMENT ON COLUMN recipes.compliance_controls IS 'JSON array of compliance requirements (e.g., ["pci", "sox", "hipaa"])';
COMMENT ON COLUMN recipes.validation_checks IS 'JSON array of validation commands to run (e.g., ["run exploit kit smoke test"])';
COMMENT ON COLUMN recipes.cve_data IS 'JSON object containing CVE metadata fetched from internet (NVD, MITRE, etc.)';
COMMENT ON COLUMN recipes.source_urls IS 'JSON array of URLs where recipe data was sourced from';
COMMENT ON COLUMN recipes.is_active IS 'Whether this recipe is available for lab creation';
COMMENT ON COLUMN recipes.created_by IS 'User who created or approved this recipe';
