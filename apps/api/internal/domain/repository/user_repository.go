package repository

import (
    "context"
    "github.com/zerozero/apps/api/internal/domain/entity"
)

// UserRepository defines the interface for user data access
type UserRepository interface {
    // GetByID retrieves a user by their ID
    GetByID(ctx context.Context, id string) (*entity.User, error)

    // GetByClerkID retrieves a user by their Clerk ID
    GetByClerkID(ctx context.Context, clerkID string) (*entity.User, error)

    // GetByEmail retrieves a user by their email
    GetByEmail(ctx context.Context, email string) (*entity.User, error)

    // Create creates a new user
    Create(ctx context.Context, user *entity.User) (*entity.User, error)

    // Update updates an existing user
    Update(ctx context.Context, user *entity.User) (*entity.User, error)

    // Delete deletes a user
    Delete(ctx context.Context, id string) error

    // List lists users with pagination
    List(ctx context.Context, limit, offset int) ([]*entity.User, error)

    // Count counts total users
    Count(ctx context.Context) (int64, error)
}