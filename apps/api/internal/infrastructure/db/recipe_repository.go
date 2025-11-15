package db

import (
	"context"

	"github.com/google/uuid"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/pkg/errors"
	"gorm.io/gorm"
)

// RecipeRepository is the GORM implementation of the recipe repository
type RecipeRepository struct {
	db *gorm.DB
}

// NewRecipeRepository creates a new recipe repository using GORM
func NewRecipeRepository(db *gorm.DB) repository.RecipeRepository {
	return &RecipeRepository{
		db: db,
	}
}

// GetByID implements repository.RecipeRepository
func (r *RecipeRepository) GetByID(ctx context.Context, id string) (*entity.Recipe, error) {
	var recipe entity.Recipe
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&recipe).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Recipe")
		}
		return nil, errors.NewDatabaseError("Failed to get recipe by ID").WithError(err)
	}
	return &recipe, nil
}

// GetByIntentID implements repository.RecipeRepository
func (r *RecipeRepository) GetByIntentID(ctx context.Context, intentID string) (*entity.Recipe, error) {
	var recipe entity.Recipe
	err := r.db.WithContext(ctx).Where("intent_id = ?", intentID).First(&recipe).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Recipe")
		}
		return nil, errors.NewDatabaseError("Failed to get recipe by intent ID").WithError(err)
	}
	return &recipe, nil
}

// GetByUserID implements repository.RecipeRepository
func (r *RecipeRepository) GetByUserID(ctx context.Context, userID string, limit, offset int) ([]*entity.Recipe, error) {
	var recipes []*entity.Recipe
	err := r.db.WithContext(ctx).
		Where("created_by = ?", userID).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&recipes).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get recipes by user ID").WithError(err)
	}

	return recipes, nil
}

// GetActive implements repository.RecipeRepository
func (r *RecipeRepository) GetActive(ctx context.Context, limit, offset int) ([]*entity.Recipe, error) {
	var recipes []*entity.Recipe
	err := r.db.WithContext(ctx).
		Where("is_active = ?", true).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&recipes).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get active recipes").WithError(err)
	}

	return recipes, nil
}

// GetBySoftware implements repository.RecipeRepository
func (r *RecipeRepository) GetBySoftware(ctx context.Context, software string, limit, offset int) ([]*entity.Recipe, error) {
	var recipes []*entity.Recipe
	err := r.db.WithContext(ctx).
		Where("software = ?", software).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&recipes).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get recipes by software").WithError(err)
	}

	return recipes, nil
}

// Search implements repository.RecipeRepository
func (r *RecipeRepository) Search(ctx context.Context, query string, limit, offset int) ([]*entity.Recipe, error) {
	var recipes []*entity.Recipe
	searchPattern := "%" + query + "%"

	err := r.db.WithContext(ctx).
		Where("name ILIKE ? OR description ILIKE ? OR software ILIKE ?", searchPattern, searchPattern, searchPattern).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&recipes).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to search recipes").WithError(err)
	}

	return recipes, nil
}

// Create implements repository.RecipeRepository
func (r *RecipeRepository) Create(ctx context.Context, recipe *entity.Recipe) (*entity.Recipe, error) {
	if recipe.ID == "" {
		recipe.ID = uuid.New().String()
	}

	err := r.db.WithContext(ctx).Create(recipe).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create recipe").WithError(err)
	}

	return recipe, nil
}

// Update implements repository.RecipeRepository
func (r *RecipeRepository) Update(ctx context.Context, recipe *entity.Recipe) (*entity.Recipe, error) {
	err := r.db.WithContext(ctx).Save(recipe).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to update recipe").WithError(err)
	}

	return recipe, nil
}

// Delete implements repository.RecipeRepository
func (r *RecipeRepository) Delete(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).Where("id = ?", id).Delete(&entity.Recipe{}).Error
	if err != nil {
		return errors.NewDatabaseError("Failed to delete recipe").WithError(err)
	}

	return nil
}

// List implements repository.RecipeRepository
func (r *RecipeRepository) List(ctx context.Context, limit, offset int) ([]*entity.Recipe, error) {
	var recipes []*entity.Recipe
	err := r.db.WithContext(ctx).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&recipes).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to list recipes").WithError(err)
	}

	return recipes, nil
}

// Count implements repository.RecipeRepository
func (r *RecipeRepository) Count(ctx context.Context) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&entity.Recipe{}).
		Count(&count).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count recipes").WithError(err)
	}

	return count, nil
}

// CountActive implements repository.RecipeRepository
func (r *RecipeRepository) CountActive(ctx context.Context) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&entity.Recipe{}).
		Where("is_active = ?", true).
		Count(&count).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count active recipes").WithError(err)
	}

	return count, nil
}

// Activate implements repository.RecipeRepository
func (r *RecipeRepository) Activate(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).
		Model(&entity.Recipe{}).
		Where("id = ?", id).
		Update("is_active", true).Error

	if err != nil {
		return errors.NewDatabaseError("Failed to activate recipe").WithError(err)
	}

	return nil
}

// Deactivate implements repository.RecipeRepository
func (r *RecipeRepository) Deactivate(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).
		Model(&entity.Recipe{}).
		Where("id = ?", id).
		Update("is_active", false).Error

	if err != nil {
		return errors.NewDatabaseError("Failed to deactivate recipe").WithError(err)
	}

	return nil
}

// IntentRepository is the GORM implementation of the intent repository
type IntentRepository struct {
	db *gorm.DB
}

// NewIntentRepository creates a new intent repository using GORM
func NewIntentRepository(db *gorm.DB) repository.IntentRepository {
	return &IntentRepository{
		db: db,
	}
}

// GetByID implements repository.IntentRepository
func (r *IntentRepository) GetByID(ctx context.Context, id string) (*entity.Intent, error) {
	var intent entity.Intent
	err := r.db.WithContext(ctx).Where("id = ?", id).First(&intent).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Intent")
		}
		return nil, errors.NewDatabaseError("Failed to get intent by ID").WithError(err)
	}
	return &intent, nil
}

// GetBySessionID implements repository.IntentRepository
func (r *IntentRepository) GetBySessionID(ctx context.Context, sessionID string) (*entity.Intent, error) {
	var intent entity.Intent
	err := r.db.WithContext(ctx).Where("session_id = ?", sessionID).First(&intent).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, errors.NewNotFound("Intent")
		}
		return nil, errors.NewDatabaseError("Failed to get intent by session ID").WithError(err)
	}
	return &intent, nil
}

// GetByStatus implements repository.IntentRepository
func (r *IntentRepository) GetByStatus(ctx context.Context, status entity.IntentStatus, limit, offset int) ([]*entity.Intent, error) {
	var intents []*entity.Intent
	err := r.db.WithContext(ctx).
		Where("status = ?", string(status)).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&intents).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to get intents by status").WithError(err)
	}

	return intents, nil
}

// Create implements repository.IntentRepository
func (r *IntentRepository) Create(ctx context.Context, intent *entity.Intent) (*entity.Intent, error) {
	if intent.ID == "" {
		intent.ID = uuid.New().String()
	}

	err := r.db.WithContext(ctx).Create(intent).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to create intent").WithError(err)
	}

	return intent, nil
}

// Update implements repository.IntentRepository
func (r *IntentRepository) Update(ctx context.Context, intent *entity.Intent) (*entity.Intent, error) {
	err := r.db.WithContext(ctx).Save(intent).Error
	if err != nil {
		return nil, errors.NewDatabaseError("Failed to update intent").WithError(err)
	}

	return intent, nil
}

// Delete implements repository.IntentRepository
func (r *IntentRepository) Delete(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).Where("id = ?", id).Delete(&entity.Intent{}).Error
	if err != nil {
		return errors.NewDatabaseError("Failed to delete intent").WithError(err)
	}

	return nil
}

// List implements repository.IntentRepository
func (r *IntentRepository) List(ctx context.Context, limit, offset int) ([]*entity.Intent, error) {
	var intents []*entity.Intent
	err := r.db.WithContext(ctx).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&intents).Error

	if err != nil {
		return nil, errors.NewDatabaseError("Failed to list intents").WithError(err)
	}

	return intents, nil
}

// Count implements repository.IntentRepository
func (r *IntentRepository) Count(ctx context.Context) (int64, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&entity.Intent{}).
		Count(&count).Error

	if err != nil {
		return 0, errors.NewDatabaseError("Failed to count intents").WithError(err)
	}

	return count, nil
}

// Approve implements repository.IntentRepository
func (r *IntentRepository) Approve(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).
		Model(&entity.Intent{}).
		Where("id = ?", id).
		Update("status", string(entity.IntentStatusApproved)).Error

	if err != nil {
		return errors.NewDatabaseError("Failed to approve intent").WithError(err)
	}

	return nil
}

// Reject implements repository.IntentRepository
func (r *IntentRepository) Reject(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).
		Model(&entity.Intent{}).
		Where("id = ?", id).
		Update("status", string(entity.IntentStatusRejected)).Error

	if err != nil {
		return errors.NewDatabaseError("Failed to reject intent").WithError(err)
	}

	return nil
}
