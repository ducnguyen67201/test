package db

import (
    "context"
    "database/sql"
    "github.com/google/uuid"
    "github.com/jackc/pgx/v5/pgxpool"
    "github.com/zerozero/apps/api/internal/domain/entity"
    "github.com/zerozero/apps/api/internal/domain/repository"
    "github.com/zerozero/apps/api/pkg/errors"
)

// UserRepository is the PostgreSQL implementation of the user repository
type UserRepository struct {
    db *pgxpool.Pool
}

// NewUserRepository creates a new user repository
func NewUserRepository(db *pgxpool.Pool) repository.UserRepository {
    return &UserRepository{
        db: db,
    }
}

// GetByID implements repository.UserRepository
func (r *UserRepository) GetByID(ctx context.Context, id string) (*entity.User, error) {
    query := `
        SELECT id, clerk_id, email, first_name, last_name, avatar_url, created_at, updated_at
        FROM users
        WHERE id = $1
    `

    var user entity.User
    err := r.db.QueryRow(ctx, query, id).Scan(
        &user.ID,
        &user.ClerkID,
        &user.Email,
        &user.FirstName,
        &user.LastName,
        &user.AvatarURL,
        &user.CreatedAt,
        &user.UpdatedAt,
    )

    if err != nil {
        if err == sql.ErrNoRows {
            return nil, errors.NewNotFound("User")
        }   
        return nil, errors.NewDatabaseError("Failed to get user by ID").WithError(err)
    }

    return &user, nil
}

// GetByClerkID implements repository.UserRepository
func (r *UserRepository) GetByClerkID(ctx context.Context, clerkID string) (*entity.User, error) {
    query := `
        SELECT id, clerk_id, email, first_name, last_name, avatar_url, created_at, updated_at
        FROM users
        WHERE clerk_id = $1
    `

    var user entity.User
    err := r.db.QueryRow(ctx, query, clerkID).Scan(
        &user.ID,
        &user.ClerkID,
        &user.Email,
        &user.FirstName,
        &user.LastName,
        &user.AvatarURL,
        &user.CreatedAt,
        &user.UpdatedAt,
    )

    if err != nil {
        if err == sql.ErrNoRows {
            return nil, errors.NewNotFound("User")
        }
        return nil, errors.NewDatabaseError("Failed to get user by Clerk ID").WithError(err)
    }

    return &user, nil
}

// GetByEmail implements repository.UserRepository
func (r *UserRepository) GetByEmail(ctx context.Context, email string) (*entity.User, error) {
    query := `
        SELECT id, clerk_id, email, first_name, last_name, avatar_url, created_at, updated_at
        FROM users
        WHERE email = $1
    `

    var user entity.User
    err := r.db.QueryRow(ctx, query, email).Scan(
        &user.ID,
        &user.ClerkID,
        &user.Email,
        &user.FirstName,
        &user.LastName,
        &user.AvatarURL,
        &user.CreatedAt,
        &user.UpdatedAt,
    )

    if err != nil {
        if err == sql.ErrNoRows {
            return nil, errors.NewNotFound("User")
        }
        return nil, errors.NewDatabaseError("Failed to get user by email").WithError(err)
    }

    return &user, nil
}

// Create implements repository.UserRepository
func (r *UserRepository) Create(ctx context.Context, user *entity.User) (*entity.User, error) {
    if user.ID == "" {
        user.ID = uuid.New().String()
    }

    query := `
        INSERT INTO users (id, clerk_id, email, first_name, last_name, avatar_url)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, clerk_id, email, first_name, last_name, avatar_url, created_at, updated_at
    `

    var created entity.User
    err := r.db.QueryRow(ctx, query,
        user.ID,
        user.ClerkID,
        user.Email,
        user.FirstName,
        user.LastName,
        user.AvatarURL,
    ).Scan(
        &created.ID,
        &created.ClerkID,
        &created.Email,
        &created.FirstName,
        &created.LastName,
        &created.AvatarURL,
        &created.CreatedAt,
        &created.UpdatedAt,
    )

    if err != nil {
        return nil, errors.NewDatabaseError("Failed to create user").WithError(err)
    }

    return &created, nil
}

// Update implements repository.UserRepository
func (r *UserRepository) Update(ctx context.Context, user *entity.User) (*entity.User, error) {
    query := `
        UPDATE users
        SET first_name = $2, last_name = $3, avatar_url = $4, email = $5, updated_at = NOW()
        WHERE id = $1
        RETURNING id, clerk_id, email, first_name, last_name, avatar_url, created_at, updated_at
    `

    var updated entity.User
    err := r.db.QueryRow(ctx, query,
        user.ID,
        user.FirstName,
        user.LastName,
        user.AvatarURL,
        user.Email,
    ).Scan(
        &updated.ID,
        &updated.ClerkID,
        &updated.Email,
        &updated.FirstName,
        &updated.LastName,
        &updated.AvatarURL,
        &updated.CreatedAt,
        &updated.UpdatedAt,
    )

    if err != nil {
        if err == sql.ErrNoRows {
            return nil, errors.NewNotFound("User")
        }
        return nil, errors.NewDatabaseError("Failed to update user").WithError(err)
    }

    return &updated, nil
}

// Delete implements repository.UserRepository
func (r *UserRepository) Delete(ctx context.Context, id string) error {
    query := `DELETE FROM users WHERE id = $1`

    result, err := r.db.Exec(ctx, query, id)
    if err != nil {
        return errors.NewDatabaseError("Failed to delete user").WithError(err)
    }

    if result.RowsAffected() == 0 {
        return errors.NewNotFound("User")
    }

    return nil
}

// List implements repository.UserRepository
func (r *UserRepository) List(ctx context.Context, limit, offset int) ([]*entity.User, error) {
    query := `
        SELECT id, clerk_id, email, first_name, last_name, avatar_url, created_at, updated_at
        FROM users
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
    `

    rows, err := r.db.Query(ctx, query, limit, offset)
    if err != nil {
        return nil, errors.NewDatabaseError("Failed to list users").WithError(err)
    }
    defer rows.Close()

    var users []*entity.User
    for rows.Next() {
        var user entity.User
        err := rows.Scan(
            &user.ID,
            &user.ClerkID,
            &user.Email,
            &user.FirstName,
            &user.LastName,
            &user.AvatarURL,
            &user.CreatedAt,
            &user.UpdatedAt,
        )
        if err != nil {
            return nil, errors.NewDatabaseError("Failed to scan user").WithError(err)
        }
        users = append(users, &user)
    }

    return users, nil
}

// Count implements repository.UserRepository
func (r *UserRepository) Count(ctx context.Context) (int64, error) {
    query := `SELECT COUNT(*) FROM users`

    var count int64
    err := r.db.QueryRow(ctx, query).Scan(&count)
    if err != nil {
        return 0, errors.NewDatabaseError("Failed to count users").WithError(err)
    }

    return count, nil
}