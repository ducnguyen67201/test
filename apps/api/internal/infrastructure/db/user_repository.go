package db

import (
	"context"

	"github.com/google/uuid"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/pkg/errors"
	"gorm.io/gorm"
)

// UserRepository is the GORM implementation of the user repository
type UserRepository struct {
	db *gorm.DB
}

// NewUserRepository creates a new user repository using GORM
func NewUserRepository(db *gorm.DB) repository.UserRepository {
	return &UserRepository{
		db: db,
	}
}

// GetByID implements repository.UserRepository
func (r *UserRepository) GetByID(ctx context.Context, id string) (*entity.User, error) {
	var user entity.User
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&user).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("User")
		}
		return nil, errors.NewDatabaseError("Failed to get user by ID").WithError(err)
	}
	return &user, nil
}

// GetByClerkID implements repository.UserRepository
func (r *UserRepository) GetByClerkID(ctx context.Context, clerkID string) (*entity.User, error) {
	var user entity.User
	err := r.db.WithContext(ctx).Where("clerk_id = ?", clerkID).First(&user).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("User")
		}
		return nil, errors.NewDatabaseError("Failed to get user by Clerk ID").WithError(err)
	}
	return &user, nil
}

// GetByEmail implements repository.UserRepository
func (r *UserRepository) GetByEmail(ctx context.Context, email string) (*entity.User, error) {
	var user entity.User
	err := r.db.WithContext(ctx).Where("email = ?", email).First(&user).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
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

	err := r.db.WithContext(ctx).Create(user).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create user").WithError(err)
	}

	return user, nil
}

// Update implements repository.UserRepository
func (r *UserRepository) Update(ctx context.Context, user *entity.User) (*entity.User, error) {
	err := r.db.WithContext(ctx).Save(user).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to update user").WithError(err)
	}

	// Check if user exists
	var count int64
	r.db.WithContext(ctx).Model(&entity.User{}).Where("id = ?", user.ID).Count(&count)
	if count == 0 {
		return nil, errors.NewNotFound("User")
	}

	return user, nil
}

// Delete implements repository.UserRepository
func (r *UserRepository) Delete(ctx context.Context, id string) error {
	result := r.db.WithContext(ctx).Delete(&entity.User{}, "id = ?", id)
	if result.Error != nil {
		return errors.NewDatabaseError("Failed to delete user").WithError(result.Error)
	}

	if result.RowsAffected == 0 {
		return errors.NewNotFound("User")
	}

	return nil
}

// List implements repository.UserRepository
func (r *UserRepository) List(ctx context.Context, limit, offset int) ([]*entity.User, error) {
	var users []*entity.User
	err := r.db.WithContext(ctx).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&users).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to list users").WithError(err)
	}

	return users, nil
}

// Count implements repository.UserRepository
func (r *UserRepository) Count(ctx context.Context) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).Model(&entity.User{}).Count(&count).Error
	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count users").WithError(err)
	}

	return count, nil
}
