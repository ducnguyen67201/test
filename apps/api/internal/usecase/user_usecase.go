package usecase

import (
    "context"
    "fmt"
    "github.com/zerozero/apps/api/internal/domain/entity"
    "github.com/zerozero/apps/api/internal/domain/repository"
    "github.com/zerozero/apps/api/pkg/errors"
    "github.com/zerozero/apps/api/pkg/logger"
)

// UserUseCase handles user-related business logic
type UserUseCase interface {
    // GetOrCreateUser gets an existing user or creates a new one
    GetOrCreateUser(ctx context.Context, clerkID, email, firstName, lastName, avatarURL string) (*entity.User, bool, error)

    // UpdateProfile updates a user's profile
    UpdateProfile(ctx context.Context, clerkID, firstName, lastName, avatarURL string) (*entity.User, error)

    // GetUserByClerkID gets a user by their Clerk ID
    GetUserByClerkID(ctx context.Context, clerkID string) (*entity.User, error)

    // GetUserByID gets a user by their ID
    GetUserByID(ctx context.Context, id string) (*entity.User, error)
}

// userUseCase is the concrete implementation
type userUseCase struct {
    userRepo repository.UserRepository
    logger   logger.Logger
}

// NewUserUseCase creates a new user use case
func NewUserUseCase(userRepo repository.UserRepository, logger logger.Logger) UserUseCase {
    return &userUseCase{
        userRepo: userRepo,
        logger:   logger,
    }
}

// GetOrCreateUser implements UserUseCase
func (uc *userUseCase) GetOrCreateUser(ctx context.Context, clerkID, email, firstName, lastName, avatarURL string) (*entity.User, bool, error) {
    // Try to get existing user
    existingUser, err := uc.userRepo.GetByClerkID(ctx, clerkID)
    if err == nil && existingUser != nil {
        // User exists, check if we need to update
        needsUpdate := false
        if existingUser.Email != email ||
           existingUser.FirstName != firstName ||
           existingUser.LastName != lastName ||
           existingUser.AvatarURL != avatarURL {
            needsUpdate = true
        }

        if needsUpdate {
            existingUser.Email = email
            existingUser.FirstName = firstName
            existingUser.LastName = lastName
            existingUser.AvatarURL = avatarURL

            updatedUser, err := uc.userRepo.Update(ctx, existingUser)
            if err != nil {
                uc.logger.Error("Failed to update user", logger.Error(err))
                return nil, false, errors.NewInternal("Failed to update user").WithError(err)
            }
            return updatedUser, false, nil
        }

        return existingUser, false, nil
    }

    // User doesn't exist, create new one
    newUser := &entity.User{
        ClerkID:   clerkID,
        Email:     email,
        FirstName: firstName,
        LastName:  lastName,
        AvatarURL: avatarURL,
    }

    // Validate user
    if err := newUser.Validate(); err != nil {
        return nil, false, errors.NewValidation(err.Error())
    }

    createdUser, err := uc.userRepo.Create(ctx, newUser)
    if err != nil {
        uc.logger.Error("Failed to create user", logger.Error(err))
        return nil, false, errors.NewInternal("Failed to create user").WithError(err)
    }

    uc.logger.Info("Created new user", logger.String("user_id", createdUser.ID), logger.String("clerk_id", clerkID))
    return createdUser, true, nil
}

// UpdateProfile implements UserUseCase
func (uc *userUseCase) UpdateProfile(ctx context.Context, clerkID, firstName, lastName, avatarURL string) (*entity.User, error) {
    // Get existing user
    user, err := uc.userRepo.GetByClerkID(ctx, clerkID)
    if err != nil {
        if errors.IsNotFound(err) {
            return nil, errors.NewNotFound("User")
        }
        uc.logger.Error("Failed to get user", logger.Error(err))
        return nil, errors.NewInternal("Failed to get user").WithError(err)
    }

    // Update fields
    if firstName != "" {
        user.FirstName = firstName
    }
    if lastName != "" {
        user.LastName = lastName
    }
    if avatarURL != "" {
        user.AvatarURL = avatarURL
    }

    // Update in database
    updatedUser, err := uc.userRepo.Update(ctx, user)
    if err != nil {
        uc.logger.Error("Failed to update user profile", logger.Error(err))
        return nil, errors.NewInternal("Failed to update profile").WithError(err)
    }

    uc.logger.Info("Updated user profile", logger.String("user_id", updatedUser.ID))
    return updatedUser, nil
}

// GetUserByClerkID implements UserUseCase
func (uc *userUseCase) GetUserByClerkID(ctx context.Context, clerkID string) (*entity.User, error) {
    user, err := uc.userRepo.GetByClerkID(ctx, clerkID)
    if err != nil {
        if errors.IsNotFound(err) {
            return nil, errors.NewNotFound("User")
        }
        uc.logger.Error("Failed to get user by Clerk ID", logger.Error(err))
        return nil, errors.NewInternal("Failed to get user").WithError(err)
    }

    if user == nil {
        return nil, errors.NewNotFound("User")
    }

    return user, nil
}

// GetUserByID implements UserUseCase
func (uc *userUseCase) GetUserByID(ctx context.Context, id string) (*entity.User, error) {
    user, err := uc.userRepo.GetByID(ctx, id)
    if err != nil {
        if errors.IsNotFound(err) {
            return nil, errors.NewNotFound(fmt.Sprintf("User with ID %s", id))
        }
        uc.logger.Error("Failed to get user by ID", logger.Error(err))
        return nil, errors.NewInternal("Failed to get user").WithError(err)
    }

    if user == nil {
        return nil, errors.NewNotFound(fmt.Sprintf("User with ID %s", id))
    }

    return user, nil
}