-- name: GetUserByClerkID :one
SELECT * FROM users
WHERE clerk_id = $1;

-- name: GetUserByID :one
SELECT * FROM users
WHERE id = $1;

-- name: GetUserByEmail :one
SELECT * FROM users
WHERE email = $1;

-- name: CreateUser :one
INSERT INTO users (
    clerk_id,
    email,
    first_name,
    last_name,
    avatar_url,
    theme,
    language,
    notifications_enabled,
    email_notifications
) VALUES (
    $1, $2, $3, $4, $5,
    COALESCE($6, 'system'),
    COALESCE($7, 'en'),
    COALESCE($8, true),
    COALESCE($9, true)
) RETURNING *;

-- name: UpdateUser :one
UPDATE users
SET
    first_name = COALESCE(NULLIF($2, ''), first_name),
    last_name = COALESCE(NULLIF($3, ''), last_name),
    avatar_url = COALESCE(NULLIF($4, ''), avatar_url),
    theme = COALESCE(NULLIF($5, ''), theme),
    language = COALESCE(NULLIF($6, ''), language),
    notifications_enabled = COALESCE($7, notifications_enabled),
    email_notifications = COALESCE($8, email_notifications),
    updated_at = NOW()
WHERE id = $1
RETURNING *;

-- name: UpdateUserByClerkID :one
UPDATE users
SET
    first_name = COALESCE(NULLIF($2, ''), first_name),
    last_name = COALESCE(NULLIF($3, ''), last_name),
    avatar_url = COALESCE(NULLIF($4, ''), avatar_url),
    email = COALESCE(NULLIF($5, ''), email),
    updated_at = NOW()
WHERE clerk_id = $1
RETURNING *;

-- name: UpdateUserPreferences :one
UPDATE users
SET
    theme = COALESCE(NULLIF($2, ''), theme),
    language = COALESCE(NULLIF($3, ''), language),
    notifications_enabled = COALESCE($4, notifications_enabled),
    email_notifications = COALESCE($5, email_notifications),
    updated_at = NOW()
WHERE id = $1
RETURNING *;

-- name: DeleteUser :exec
DELETE FROM users
WHERE id = $1;

-- name: ListUsers :many
SELECT * FROM users
ORDER BY created_at DESC
LIMIT $1 OFFSET $2;

-- name: CountUsers :one
SELECT COUNT(*) FROM users;
