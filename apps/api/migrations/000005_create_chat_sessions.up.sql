-- Create chat_sessions table for LLM Chat-to-Recipe feature
-- This table stores conversation sessions between users and the LLM for recipe generation

-- Create ENUM types for chat_sessions
CREATE TYPE chat_session_status AS ENUM ('open', 'finalizing', 'closed');

-- Create chat_sessions table
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID,
    status chat_session_status NOT NULL DEFAULT 'open',
    llm_model VARCHAR(100) NOT NULL DEFAULT 'gpt-4o',
    token_usage INTEGER NOT NULL DEFAULT 0,
    max_tokens INTEGER NOT NULL DEFAULT 50000,
    max_duration_minutes INTEGER NOT NULL DEFAULT 30,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_status ON chat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_created_at ON chat_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_status ON chat_sessions(user_id, status);

-- Add table comments for documentation
COMMENT ON TABLE chat_sessions IS 'LLM conversation sessions for recipe generation from user intent';
COMMENT ON COLUMN chat_sessions.project_id IS 'Optional project association for organizing recipes';
COMMENT ON COLUMN chat_sessions.status IS 'Session lifecycle: open (active), finalizing (extracting intent), closed (completed)';
COMMENT ON COLUMN chat_sessions.llm_model IS 'LLM model used for this session (e.g., gpt-4o, claude-sonnet)';
COMMENT ON COLUMN chat_sessions.token_usage IS 'Total tokens consumed in this session for cost tracking';
COMMENT ON COLUMN chat_sessions.max_tokens IS 'Maximum allowed tokens for this session (budget control)';
COMMENT ON COLUMN chat_sessions.max_duration_minutes IS 'Maximum session duration in minutes before auto-close';
