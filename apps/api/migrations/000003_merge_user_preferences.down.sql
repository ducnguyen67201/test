-- Revert: Separate user_preferences back into its own table
-- Recreate user_preferences table
CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    theme VARCHAR(50) DEFAULT 'light',
    language VARCHAR(10) DEFAULT 'en',
    notifications_enabled BOOLEAN DEFAULT true,
    email_notifications BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Migrate data back from users to user_preferences
INSERT INTO user_preferences (user_id, theme, language, notifications_enabled, email_notifications, created_at, updated_at)
SELECT id, theme, language, notifications_enabled, email_notifications, created_at, updated_at
FROM users
WHERE theme IS NOT NULL OR language IS NOT NULL OR notifications_enabled IS NOT NULL OR email_notifications IS NOT NULL;

-- Create index on user_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id);

-- Add comment
COMMENT ON TABLE user_preferences IS 'User application preferences and settings';

-- Remove preference columns from users table
ALTER TABLE users DROP COLUMN IF EXISTS theme;
ALTER TABLE users DROP COLUMN IF EXISTS language;
ALTER TABLE users DROP COLUMN IF EXISTS notifications_enabled;
ALTER TABLE users DROP COLUMN IF EXISTS email_notifications;
