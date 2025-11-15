package usecase

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/internal/infrastructure/services"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/llm"
	"github.com/zerozero/apps/api/pkg/logger"
)

// RecipeUseCase handles recipe business logic
type RecipeUseCase interface {
	// CreateFromIntent creates a recipe from an approved intent
	CreateFromIntent(ctx context.Context, intentID string, userID string) (*entity.Recipe, error)

	// CreateManual creates a recipe manually (not from intent)
	CreateManual(ctx context.Context, input *CreateRecipeInput, userID string) (*entity.Recipe, error)

	// GetByID retrieves a recipe by ID
	GetByID(ctx context.Context, recipeID string) (*entity.Recipe, error)

	// GetActive retrieves active recipes
	GetActive(ctx context.Context, limit, offset int) ([]*entity.Recipe, error)

	// GetBySoftware retrieves recipes for specific software
	GetBySoftware(ctx context.Context, software string, limit, offset int) ([]*entity.Recipe, error)

	// Search searches recipes by query
	Search(ctx context.Context, query string, limit, offset int) ([]*entity.Recipe, error)

	// Update updates a recipe
	Update(ctx context.Context, recipeID string, input *UpdateRecipeInput) (*entity.Recipe, error)

	// Delete deletes a recipe
	Delete(ctx context.Context, recipeID string) error

	// Activate activates a recipe
	Activate(ctx context.Context, recipeID string) error

	// Deactivate deactivates a recipe
	Deactivate(ctx context.Context, recipeID string) error

	// EnrichWithCVEData fetches CVE data for a recipe
	EnrichWithCVEData(ctx context.Context, recipeID string) (*entity.Recipe, error)

	// ValidateRecipe validates a recipe against guardrails
	ValidateRecipe(ctx context.Context, recipe *entity.Recipe) (*RecipeValidationResult, error)
}

// recipeUseCase is the concrete implementation
type recipeUseCase struct {
	recipeRepo       repository.RecipeRepository
	intentRepo       repository.IntentRepository
	webSearchService services.WebSearchService
	validatorService services.ValidatorService
	log              logger.Logger
}

// NewRecipeUseCase creates a new recipe use case
func NewRecipeUseCase(
	recipeRepo repository.RecipeRepository,
	intentRepo repository.IntentRepository,
	webSearchService services.WebSearchService,
	validatorService services.ValidatorService,
	log logger.Logger,
) RecipeUseCase {
	return &recipeUseCase{
		recipeRepo:       recipeRepo,
		intentRepo:       intentRepo,
		webSearchService: webSearchService,
		validatorService: validatorService,
		log:              log,
	}
}

// CreateRecipeInput represents input for creating a recipe manually
type CreateRecipeInput struct {
	Name                string                 `json:"name"`
	Description         string                 `json:"description"`
	Software            string                 `json:"software"`
	VersionConstraint   string                 `json:"version_constraint"`
	OS                  string                 `json:"os"`
	Packages            []entity.RecipePackage `json:"packages"`
	NetworkRequirements string                 `json:"network_requirements"`
	ComplianceControls  []string               `json:"compliance_controls"`
	ValidationChecks    []string               `json:"validation_checks"`
	IsActive            bool                   `json:"is_active"`
}

// UpdateRecipeInput represents input for updating a recipe
type UpdateRecipeInput struct {
	Name                *string  `json:"name,omitempty"`
	Description         *string  `json:"description,omitempty"`
	NetworkRequirements *string  `json:"network_requirements,omitempty"`
	ComplianceControls  []string `json:"compliance_controls,omitempty"`
	ValidationChecks    []string `json:"validation_checks,omitempty"`
	IsActive            *bool    `json:"is_active,omitempty"`
}

// RecipeValidationResult contains validation results
type RecipeValidationResult struct {
	Passed   bool              `json:"passed"`
	Errors   []ValidationError `json:"errors,omitempty"`
	Warnings []ValidationError `json:"warnings,omitempty"`
}

// ValidationError represents a validation error
type ValidationError struct {
	Field    string `json:"field"`
	Message  string `json:"message"`
	Severity string `json:"severity"` // "error", "warning"
}

// CreateFromIntent implements RecipeUseCase
func (uc *recipeUseCase) CreateFromIntent(ctx context.Context, intentID string, userID string) (*entity.Recipe, error) {
	uc.log.Info("Creating recipe from intent",
		logger.String("intent_id", intentID),
		logger.String("user_id", userID))

	// Get intent
	intent, err := uc.intentRepo.GetByID(ctx, intentID)
	if err != nil {
		return nil, err
	}

	// Check if intent is approved
	if !intent.IsApproved() {
		return nil, errors.NewValidation("intent_status: Intent must be approved before creating recipe")
	}

	// Check if recipe already exists for this intent
	existingRecipe, err := uc.recipeRepo.GetByIntentID(ctx, intentID)
	if err == nil && existingRecipe != nil {
		return nil, errors.NewValidation("intent_id: Recipe already exists for this intent")
	}

	// Parse intent payload
	var intentPayload entity.IntentPayload

	// Debug: log the raw payload
	uc.log.Info("Parsing intent payload",
		logger.String("intent_id", intentID),
		logger.String("payload", string(intent.Payload)))

	if err := json.Unmarshal(intent.Payload, &intentPayload); err != nil {
		uc.log.Error("Failed to unmarshal intent payload",
			logger.Error(err),
			logger.String("payload", string(intent.Payload)))
		return nil, errors.NewInternal("Failed to parse intent payload").WithError(err)
	}

	uc.log.Info("Successfully parsed intent payload",
		logger.String("name", intentPayload.Name),
		logger.String("software", intentPayload.Software))

	// Create recipe from intent
	recipe := &entity.Recipe{
		IntentID:            &intent.ID,
		Name:                intentPayload.Name,
		Description:         intentPayload.Description,
		Software:            intentPayload.Software,
		VersionConstraint:   intentPayload.VersionConstraint,
		OS:                  intentPayload.OS,
		NetworkRequirements: intentPayload.NetworkRequirements,
		IsActive:            intentPayload.IsActive,
		CreatedBy:           userID,
	}

	// Set packages
	if err := recipe.SetPackages(convertIntentPackages(intentPayload.Packages)); err != nil {
		return nil, errors.NewInternal("Failed to set packages").WithError(err)
	}

	// Set compliance controls
	if err := recipe.SetComplianceControls(intentPayload.ComplianceControls); err != nil {
		return nil, errors.NewInternal("Failed to set compliance controls").WithError(err)
	}

	// Set validation checks
	if err := recipe.SetValidationChecks(intentPayload.ValidationChecks); err != nil {
		return nil, errors.NewInternal("Failed to set validation checks").WithError(err)
	}

	// Set CVE data if available
	if intentPayload.CVEData != nil {
		if err := recipe.SetCVEData(intentPayload.CVEData); err != nil {
			return nil, errors.NewInternal("Failed to set CVE data").WithError(err)
		}
	}

	// Set source URLs
	if err := recipe.SetSourceURLs(intentPayload.SourceURLs); err != nil {
		return nil, errors.NewInternal("Failed to set source URLs").WithError(err)
	}

	// Validate recipe
	if err := recipe.Validate(); err != nil {
		return nil, err
	}

	// Validate against guardrails
	if uc.validatorService != nil {
		validationResult, err := uc.ValidateRecipe(ctx, recipe)
		if err != nil {
			uc.log.Warn("Guardrail validation failed", logger.Error(err))
		} else if !validationResult.Passed {
			uc.log.Warn("Recipe failed guardrail validation",
				logger.Int("error_count", len(validationResult.Errors)))
			// Don't block creation, but log warnings
		}
	}

	// Create recipe
	createdRecipe, err := uc.recipeRepo.Create(ctx, recipe)
	if err != nil {
		uc.log.Error("Failed to create recipe", logger.Error(err))
		return nil, errors.NewInternal("Failed to create recipe").WithError(err)
	}

	uc.log.Info("Recipe created from intent",
		logger.String("recipe_id", createdRecipe.ID),
		logger.String("intent_id", intentID))

	return createdRecipe, nil
}

// CreateManual implements RecipeUseCase
func (uc *recipeUseCase) CreateManual(ctx context.Context, input *CreateRecipeInput, userID string) (*entity.Recipe, error) {
	uc.log.Info("Creating recipe manually", logger.String("user_id", userID))

	recipe := &entity.Recipe{
		Name:                input.Name,
		Description:         input.Description,
		Software:            input.Software,
		VersionConstraint:   input.VersionConstraint,
		OS:                  input.OS,
		NetworkRequirements: input.NetworkRequirements,
		IsActive:            input.IsActive,
		CreatedBy:           userID,
	}

	// Set packages
	if err := recipe.SetPackages(input.Packages); err != nil {
		return nil, errors.NewInternal("Failed to set packages").WithError(err)
	}

	// Set compliance controls
	if err := recipe.SetComplianceControls(input.ComplianceControls); err != nil {
		return nil, errors.NewInternal("Failed to set compliance controls").WithError(err)
	}

	// Set validation checks
	if err := recipe.SetValidationChecks(input.ValidationChecks); err != nil {
		return nil, errors.NewInternal("Failed to set validation checks").WithError(err)
	}

	// Validate recipe
	if err := recipe.Validate(); err != nil {
		return nil, err
	}

	// Create recipe
	createdRecipe, err := uc.recipeRepo.Create(ctx, recipe)
	if err != nil {
		uc.log.Error("Failed to create recipe", logger.Error(err))
		return nil, errors.NewInternal("Failed to create recipe").WithError(err)
	}

	uc.log.Info("Recipe created manually", logger.String("recipe_id", createdRecipe.ID))
	return createdRecipe, nil
}

// GetByID implements RecipeUseCase
func (uc *recipeUseCase) GetByID(ctx context.Context, recipeID string) (*entity.Recipe, error) {
	return uc.recipeRepo.GetByID(ctx, recipeID)
}

// GetActive implements RecipeUseCase
func (uc *recipeUseCase) GetActive(ctx context.Context, limit, offset int) ([]*entity.Recipe, error) {
	return uc.recipeRepo.GetActive(ctx, limit, offset)
}

// GetBySoftware implements RecipeUseCase
func (uc *recipeUseCase) GetBySoftware(ctx context.Context, software string, limit, offset int) ([]*entity.Recipe, error) {
	return uc.recipeRepo.GetBySoftware(ctx, software, limit, offset)
}

// Search implements RecipeUseCase
func (uc *recipeUseCase) Search(ctx context.Context, query string, limit, offset int) ([]*entity.Recipe, error) {
	return uc.recipeRepo.Search(ctx, query, limit, offset)
}

// Update implements RecipeUseCase
func (uc *recipeUseCase) Update(ctx context.Context, recipeID string, input *UpdateRecipeInput) (*entity.Recipe, error) {
	uc.log.Info("Updating recipe", logger.String("recipe_id", recipeID))

	// Get existing recipe
	recipe, err := uc.recipeRepo.GetByID(ctx, recipeID)
	if err != nil {
		return nil, err
	}

	// Update fields
	if input.Name != nil {
		recipe.Name = *input.Name
	}
	if input.Description != nil {
		recipe.Description = *input.Description
	}
	if input.NetworkRequirements != nil {
		recipe.NetworkRequirements = *input.NetworkRequirements
	}
	if input.ComplianceControls != nil {
		if err := recipe.SetComplianceControls(input.ComplianceControls); err != nil {
			return nil, errors.NewInternal("Failed to set compliance controls").WithError(err)
		}
	}
	if input.ValidationChecks != nil {
		if err := recipe.SetValidationChecks(input.ValidationChecks); err != nil {
			return nil, errors.NewInternal("Failed to set validation checks").WithError(err)
		}
	}
	if input.IsActive != nil {
		recipe.IsActive = *input.IsActive
	}

	// Validate recipe
	if err := recipe.Validate(); err != nil {
		return nil, err
	}

	// Update recipe
	updatedRecipe, err := uc.recipeRepo.Update(ctx, recipe)
	if err != nil {
		uc.log.Error("Failed to update recipe", logger.Error(err))
		return nil, errors.NewInternal("Failed to update recipe").WithError(err)
	}

	uc.log.Info("Recipe updated", logger.String("recipe_id", recipeID))
	return updatedRecipe, nil
}

// Delete implements RecipeUseCase
func (uc *recipeUseCase) Delete(ctx context.Context, recipeID string) error {
	uc.log.Info("Deleting recipe", logger.String("recipe_id", recipeID))
	return uc.recipeRepo.Delete(ctx, recipeID)
}

// Activate implements RecipeUseCase
func (uc *recipeUseCase) Activate(ctx context.Context, recipeID string) error {
	uc.log.Info("Activating recipe", logger.String("recipe_id", recipeID))
	return uc.recipeRepo.Activate(ctx, recipeID)
}

// Deactivate implements RecipeUseCase
func (uc *recipeUseCase) Deactivate(ctx context.Context, recipeID string) error {
	uc.log.Info("Deactivating recipe", logger.String("recipe_id", recipeID))
	return uc.recipeRepo.Deactivate(ctx, recipeID)
}

// EnrichWithCVEData implements RecipeUseCase
func (uc *recipeUseCase) EnrichWithCVEData(ctx context.Context, recipeID string) (*entity.Recipe, error) {
	uc.log.Info("Enriching recipe with CVE data", logger.String("recipe_id", recipeID))

	// Get recipe
	recipe, err := uc.recipeRepo.GetByID(ctx, recipeID)
	if err != nil {
		return nil, err
	}

	// Check if CVE data already exists
	existingCVE, _ := recipe.GetCVEData()
	if existingCVE != nil {
		uc.log.Info("Recipe already has CVE data", logger.String("recipe_id", recipeID))
		return recipe, nil
	}

	// Search for CVE data
	searchRequest := &llm.CVESearchRequest{
		Software:    recipe.Software,
		Version:     recipe.VersionConstraint,
		Description: recipe.Description,
	}

	cveResponse, err := uc.webSearchService.SearchCVE(ctx, searchRequest)
	if err != nil {
		uc.log.Warn("Failed to fetch CVE data", logger.Error(err))
		return recipe, nil // Don't fail if CVE search fails
	}

	// Convert to entity CVE data
	cveData := &entity.CVEData{
		ID:                  cveResponse.CVEID,
		Title:               cveResponse.Title,
		Description:         cveResponse.Description,
		Severity:            cveResponse.Severity,
		CVSSScore:           cveResponse.CVSSScore,
		ExploitabilityScore: cveResponse.ExploitabilityScore,
		References:          cveResponse.References,
	}

	// Set CVE data
	if err := recipe.SetCVEData(cveData); err != nil {
		return nil, errors.NewInternal("Failed to set CVE data").WithError(err)
	}

	// Add source URL
	if cveResponse.SourceURL != "" {
		urls := []string{cveResponse.SourceURL}
		if err := recipe.SetSourceURLs(urls); err != nil {
			uc.log.Warn("Failed to set source URLs", logger.Error(err))
		}
	}

	// Update recipe
	updatedRecipe, err := uc.recipeRepo.Update(ctx, recipe)
	if err != nil {
		return nil, errors.NewInternal("Failed to update recipe with CVE data").WithError(err)
	}

	uc.log.Info("Recipe enriched with CVE data",
		logger.String("recipe_id", recipeID),
		logger.String("cve_id", cveData.ID))

	return updatedRecipe, nil
}

// ValidateRecipe implements RecipeUseCase
func (uc *recipeUseCase) ValidateRecipe(ctx context.Context, recipe *entity.Recipe) (*RecipeValidationResult, error) {
	result := &RecipeValidationResult{
		Passed:   true,
		Errors:   []ValidationError{},
		Warnings: []ValidationError{},
	}

	// Basic validation
	if err := recipe.Validate(); err != nil {
		result.Passed = false
		result.Errors = append(result.Errors, ValidationError{
			Field:    "recipe",
			Message:  err.Error(),
			Severity: "error",
		})
		return result, nil
	}

	// Get packages
	packages, err := recipe.GetPackages()
	if err != nil {
		result.Warnings = append(result.Warnings, ValidationError{
			Field:    "packages",
			Message:  "Failed to parse packages",
			Severity: "warning",
		})
	}

	// Check package count limit
	if len(packages) > 50 {
		result.Passed = false
		result.Errors = append(result.Errors, ValidationError{
			Field:    "packages",
			Message:  fmt.Sprintf("Too many packages (%d). Maximum allowed is 50", len(packages)),
			Severity: "error",
		})
	}

	// Check for empty package names
	for i, pkg := range packages {
		if pkg.Name == "" {
			result.Passed = false
			result.Errors = append(result.Errors, ValidationError{
				Field:    fmt.Sprintf("packages[%d].name", i),
				Message:  "Package name cannot be empty",
				Severity: "error",
			})
		}
	}

	// Check OS is supported
	supportedOS := map[string]bool{
		"ubuntu2204": true,
		"ubuntu2004": true,
		"debian12":   true,
		"debian11":   true,
	}

	if !supportedOS[recipe.OS] {
		result.Warnings = append(result.Warnings, ValidationError{
			Field:    "os",
			Message:  fmt.Sprintf("OS '%s' may not be fully supported", recipe.OS),
			Severity: "warning",
		})
	}

	return result, nil
}

// convertIntentPackages converts intent packages to recipe packages
func convertIntentPackages(intentPackages []entity.IntentPackage) []entity.RecipePackage {
	recipePackages := make([]entity.RecipePackage, len(intentPackages))
	for i, pkg := range intentPackages {
		recipePackages[i] = entity.RecipePackage{
			Name:    pkg.Name,
			Version: pkg.Version,
			Source:  pkg.Source,
		}
	}
	return recipePackages
}
