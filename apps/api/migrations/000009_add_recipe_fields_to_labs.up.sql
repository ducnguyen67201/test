-- Add recipe integration fields to lab_requests table
-- This connects labs to recipes and captures user intent from chat

-- Add recipe_id and user_intent columns
ALTER TABLE lab_requests
    ADD COLUMN IF NOT EXISTS recipe_id UUID REFERENCES recipes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS user_intent TEXT;

-- Create index for recipe lookup
CREATE INDEX IF NOT EXISTS idx_lab_requests_recipe_id ON lab_requests(recipe_id);

-- Add column comments
COMMENT ON COLUMN lab_requests.recipe_id IS 'Optional foreign key to recipe template used for this lab';
COMMENT ON COLUMN lab_requests.user_intent IS 'Summarized user intent from chat session describing what they want to test';
