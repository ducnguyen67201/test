-- Create chat_messages table for storing conversation history
-- This table stores individual messages in a chat session

-- Create ENUM type for message roles
CREATE TYPE chat_message_role AS ENUM ('user', 'assistant', 'system');

-- Create chat_messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role chat_message_role NOT NULL,
    content TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chat_messages_unique_sequence UNIQUE (session_id, sequence)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_sequence ON chat_messages(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at DESC);

-- Add table comments for documentation
COMMENT ON TABLE chat_messages IS 'Individual messages in LLM conversation sessions';
COMMENT ON COLUMN chat_messages.session_id IS 'Foreign key to parent chat session';
COMMENT ON COLUMN chat_messages.role IS 'Message sender: user (human), assistant (LLM), system (prompts)';
COMMENT ON COLUMN chat_messages.content IS 'Message text content';
COMMENT ON COLUMN chat_messages.sequence IS 'Message order within session for chronological sorting';
COMMENT ON COLUMN chat_messages.tokens IS 'Token count for this specific message';
