-- Create intents table for storing extracted user intents from chat sessions
-- This table stores the structured JSON output from LLM intent extraction

-- Create ENUM type for intent status
CREATE TYPE intent_status AS ENUM ('draft', 'approved', 'rejected');

-- Create intents table
CREATE TABLE IF NOT EXISTS intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    confidence DECIMAL(3, 2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status intent_status NOT NULL DEFAULT 'draft',
    validator_errors JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT one_intent_per_session UNIQUE (session_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_intents_session_id ON intents(session_id);
CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status);
CREATE INDEX IF NOT EXISTS idx_intents_confidence ON intents(confidence);
CREATE INDEX IF NOT EXISTS idx_intents_created_at ON intents(created_at DESC);

-- Create GIN index for JSONB payload queries
CREATE INDEX IF NOT EXISTS idx_intents_payload_gin ON intents USING GIN (payload);

-- Add table comments for documentation
COMMENT ON TABLE intents IS 'Extracted user intents from chat sessions, structured as JSON for recipe creation';
COMMENT ON COLUMN intents.session_id IS 'Foreign key to parent chat session (one intent per session)';
COMMENT ON COLUMN intents.payload IS 'JSON structure containing extracted intent (name, software, packages, requirements, etc.)';
COMMENT ON COLUMN intents.confidence IS 'LLM confidence score for intent extraction (0.0 to 1.0)';
COMMENT ON COLUMN intents.status IS 'Intent lifecycle: draft (extracted), approved (user confirmed), rejected (user declined)';
COMMENT ON COLUMN intents.validator_errors IS 'JSON array of validation errors from guardrail checks';
