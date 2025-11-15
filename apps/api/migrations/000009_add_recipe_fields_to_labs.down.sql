-- Rollback recipe integration fields from lab_requests table

ALTER TABLE lab_requests
    DROP COLUMN IF EXISTS recipe_id,
    DROP COLUMN IF EXISTS user_intent;
