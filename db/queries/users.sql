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
    avatar_url
) VALUES (
    $1, $2, $3, $4, $5
) RETURNING *;

-- name: UpdateUser :one
UPDATE users
SET
    first_name = COALESCE(NULLIF($2, ''), first_name),
    last_name = COALESCE(NULLIF($3, ''), last_name),
    avatar_url = COALESCE(NULLIF($4, ''), avatar_url)
WHERE id = $1
RETURNING *;

-- name: UpdateUserByClerkID :one
UPDATE users
SET
    first_name = COALESCE(NULLIF($2, ''), first_name),
    last_name = COALESCE(NULLIF($3, ''), last_name),
    avatar_url = COALESCE(NULLIF($4, ''), avatar_url),
    email = COALESCE(NULLIF($5, ''), email)
WHERE clerk_id = $1
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