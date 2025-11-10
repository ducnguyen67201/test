-- Merge user_preferences into users table
-- Add preference columns to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS theme VARCHAR(50) DEFAULT 'system';
ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en';
ALTER TABLE users ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_notifications BOOLEAN DEFAULT true;

-- Migrate existing data from user_preferences to users table
UPDATE users u
SET
    theme = COALESCE(up.theme, 'system'),
    language = COALESCE(up.language, 'en'),
    notifications_enabled = COALESCE(up.notifications_enabled, true),
    email_notifications = COALESCE(up.email_notifications, true)
FROM user_preferences up
WHERE u.id = up.user_id;

-- Drop the user_preferences table
DROP TABLE IF EXISTS user_preferences;

-- Add comments for the new columns
COMMENT ON COLUMN users.theme IS 'User theme preference: light, dark, or system';
COMMENT ON COLUMN users.language IS 'User language preference (ISO 639-1 code)';
COMMENT ON COLUMN users.notifications_enabled IS 'Whether user has enabled in-app notifications';
COMMENT ON COLUMN users.email_notifications IS 'Whether user has enabled email notifications';
