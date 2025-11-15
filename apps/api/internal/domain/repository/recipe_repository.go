package repository

import (
	"context"
	"github.com/zerozero/apps/api/internal/domain/entity"
)

// RecipeRepository defines the interface for recipe data access
type RecipeRepository interface {
	// GetByID retrieves a recipe by its ID
	GetByID(ctx context.Context, id string) (*entity.Recipe, error)

	// GetByIntentID retrieves a recipe by the intent that created it
	GetByIntentID(ctx context.Context, intentID string) (*entity.Recipe, error)

	// GetByUserID retrieves all recipes created by a specific user
	GetByUserID(ctx context.Context, userID string, limit, offset int) ([]*entity.Recipe, error)

	// GetActive retrieves all active recipes
	GetActive(ctx context.Context, limit, offset int) ([]*entity.Recipe, error)

	// GetBySoftware retrieves recipes for a specific software
	GetBySoftware(ctx context.Context, software string, limit, offset int) ([]*entity.Recipe, error)

	// Search searches recipes by name, description, or software
	Search(ctx context.Context, query string, limit, offset int) ([]*entity.Recipe, error)

	// Create creates a new recipe
	Create(ctx context.Context, recipe *entity.Recipe) (*entity.Recipe, error)

	// Update updates an existing recipe
	Update(ctx context.Context, recipe *entity.Recipe) (*entity.Recipe, error)

	// Delete deletes a recipe
	Delete(ctx context.Context, id string) error

	// List lists recipes with pagination
	List(ctx context.Context, limit, offset int) ([]*entity.Recipe, error)

	// Count counts total recipes
	Count(ctx context.Context) (int64, error)

	// CountActive counts active recipes
	CountActive(ctx context.Context) (int64, error)

	// Activate activates a recipe
	Activate(ctx context.Context, id string) error

	// Deactivate deactivates a recipe
	Deactivate(ctx context.Context, id string) error
}

// IntentRepository defines the interface for intent data access
type IntentRepository interface {
	// GetByID retrieves an intent by its ID
	GetByID(ctx context.Context, id string) (*entity.Intent, error)

	// GetBySessionID retrieves an intent by session ID
	GetBySessionID(ctx context.Context, sessionID string) (*entity.Intent, error)

	// GetByStatus retrieves intents by status
	GetByStatus(ctx context.Context, status entity.IntentStatus, limit, offset int) ([]*entity.Intent, error)

	// Create creates a new intent
	Create(ctx context.Context, intent *entity.Intent) (*entity.Intent, error)

	// Update updates an existing intent
	Update(ctx context.Context, intent *entity.Intent) (*entity.Intent, error)

	// Delete deletes an intent
	Delete(ctx context.Context, id string) error

	// List lists intents with pagination
	List(ctx context.Context, limit, offset int) ([]*entity.Intent, error)

	// Count counts total intents
	Count(ctx context.Context) (int64, error)

	// Approve approves an intent
	Approve(ctx context.Context, id string) error

	// Reject rejects an intent
	Reject(ctx context.Context, id string) error
}
