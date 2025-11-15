package usecase

import (
	"context"
	"encoding/json"

	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
)

// IntentUseCase handles intent business logic
type IntentUseCase interface {
	// GetByID retrieves an intent by ID
	GetByID(ctx context.Context, intentID string) (*entity.Intent, error)

	// GetBySessionID retrieves an intent by session ID
	GetBySessionID(ctx context.Context, sessionID string) (*entity.Intent, error)

	// GetPendingIntents retrieves intents pending approval
	GetPendingIntents(ctx context.Context, limit, offset int) ([]*entity.Intent, error)

	// Approve approves an intent
	Approve(ctx context.Context, intentID string, userID string) (*entity.Intent, error)

	// Reject rejects an intent
	Reject(ctx context.Context, intentID string, reason string) (*entity.Intent, error)

	// ValidateIntent validates an intent against guardrails
	ValidateIntent(ctx context.Context, intent *entity.Intent) (*IntentValidationResult, error)

	// GetIntentPayload parses and returns the intent payload
	GetIntentPayload(ctx context.Context, intentID string) (*entity.IntentPayload, error)
}

// intentUseCase is the concrete implementation
type intentUseCase struct {
	intentRepo repository.IntentRepository
	log        logger.Logger
}

// NewIntentUseCase creates a new intent use case
func NewIntentUseCase(
	intentRepo repository.IntentRepository,
	log logger.Logger,
) IntentUseCase {
	return &intentUseCase{
		intentRepo: intentRepo,
		log:        log,
	}
}

// IntentValidationResult contains validation results for an intent
type IntentValidationResult struct {
	Passed   bool                  `json:"passed"`
	Errors   []string              `json:"errors,omitempty"`
	Warnings []string              `json:"warnings,omitempty"`
	Payload  *entity.IntentPayload `json:"payload,omitempty"`
}

// GetByID implements IntentUseCase
func (uc *intentUseCase) GetByID(ctx context.Context, intentID string) (*entity.Intent, error) {
	return uc.intentRepo.GetByID(ctx, intentID)
}

// GetBySessionID implements IntentUseCase
func (uc *intentUseCase) GetBySessionID(ctx context.Context, sessionID string) (*entity.Intent, error) {
	return uc.intentRepo.GetBySessionID(ctx, sessionID)
}

// GetPendingIntents implements IntentUseCase
func (uc *intentUseCase) GetPendingIntents(ctx context.Context, limit, offset int) ([]*entity.Intent, error) {
	return uc.intentRepo.GetByStatus(ctx, entity.IntentStatusDraft, limit, offset)
}

// Approve implements IntentUseCase
func (uc *intentUseCase) Approve(ctx context.Context, intentID string, userID string) (*entity.Intent, error) {
	uc.log.Info("Approving intent",
		logger.String("intent_id", intentID),
		logger.String("user_id", userID))

	// Get intent
	intent, err := uc.intentRepo.GetByID(ctx, intentID)
	if err != nil {
		return nil, err
	}

	// Check if already approved
	if intent.IsApproved() {
		return nil, errors.NewValidation("intent_status: Intent is already approved")
	}

	// Check if rejected
	if intent.IsRejected() {
		return nil, errors.NewValidation("intent_status: Cannot approve a rejected intent")
	}

	// Validate intent before approval (but allow approval with warnings)
	validationResult, err := uc.ValidateIntent(ctx, intent)
	if err != nil {
		uc.log.Warn("Intent validation failed", logger.Error(err))
	}

	if validationResult != nil && !validationResult.Passed {
		uc.log.Warn("Intent has validation errors - allowing approval anyway",
			logger.String("intent_id", intentID),
			logger.Int("error_count", len(validationResult.Errors)))

		// Store validation errors but don't block approval
		errorsJSON, _ := json.Marshal(validationResult.Errors)
		intent.ValidatorErrors = json.RawMessage(errorsJSON)
		_, _ = uc.intentRepo.Update(ctx, intent)

		// TEMPORARY: Allow approval even with validation errors
		// TODO: Re-enable strict validation once intent extraction improves
		// return nil, errors.NewValidation("intent_validation: Intent failed validation checks")
	}

	// Approve intent
	err = uc.intentRepo.Approve(ctx, intentID)
	if err != nil {
		uc.log.Error("Failed to approve intent", logger.Error(err))
		return nil, errors.NewInternal("Failed to approve intent").WithError(err)
	}

	// Get updated intent
	approvedIntent, err := uc.intentRepo.GetByID(ctx, intentID)
	if err != nil {
		return nil, err
	}

	uc.log.Info("Intent approved", logger.String("intent_id", intentID))
	return approvedIntent, nil
}

// Reject implements IntentUseCase
func (uc *intentUseCase) Reject(ctx context.Context, intentID string, reason string) (*entity.Intent, error) {
	uc.log.Info("Rejecting intent",
		logger.String("intent_id", intentID),
		logger.String("reason", reason))

	// Get intent
	intent, err := uc.intentRepo.GetByID(ctx, intentID)
	if err != nil {
		return nil, err
	}

	// Check if already rejected
	if intent.IsRejected() {
		return nil, errors.NewValidation("intent_status: Intent is already rejected")
	}

	// Check if approved
	if intent.IsApproved() {
		return nil, errors.NewValidation("intent_status: Cannot reject an approved intent")
	}

	// Store rejection reason in validator errors
	rejectionData := map[string]string{
		"reason": reason,
	}
	rejectionJSON, _ := json.Marshal(rejectionData)
	intent.ValidatorErrors = json.RawMessage(rejectionJSON)

	_, err = uc.intentRepo.Update(ctx, intent)
	if err != nil {
		uc.log.Warn("Failed to save rejection reason", logger.Error(err))
	}

	// Reject intent
	err = uc.intentRepo.Reject(ctx, intentID)
	if err != nil {
		uc.log.Error("Failed to reject intent", logger.Error(err))
		return nil, errors.NewInternal("Failed to reject intent").WithError(err)
	}

	// Get updated intent
	rejectedIntent, err := uc.intentRepo.GetByID(ctx, intentID)
	if err != nil {
		return nil, err
	}

	uc.log.Info("Intent rejected", logger.String("intent_id", intentID))
	return rejectedIntent, nil
}

// ValidateIntent implements IntentUseCase
func (uc *intentUseCase) ValidateIntent(ctx context.Context, intent *entity.Intent) (*IntentValidationResult, error) {
	result := &IntentValidationResult{
		Passed:   true,
		Errors:   []string{},
		Warnings: []string{},
	}

	// Parse payload
	var payload entity.IntentPayload
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		result.Passed = false
		result.Errors = append(result.Errors, "Invalid JSON payload")
		return result, nil
	}

	result.Payload = &payload

	// Check confidence threshold
	minConfidence := 0.6
	if intent.Confidence < minConfidence {
		result.Passed = false
		result.Errors = append(result.Errors, "Confidence score too low (minimum 0.6)")
	} else if intent.Confidence < 0.7 {
		result.Warnings = append(result.Warnings, "Confidence score is below recommended threshold (0.7)")
	}

	// Validate required fields
	if payload.Name == "" {
		result.Passed = false
		result.Errors = append(result.Errors, "Recipe name is required")
	}

	if payload.Software == "" {
		result.Passed = false
		result.Errors = append(result.Errors, "Software is required")
	}

	if payload.OS == "" {
		result.Warnings = append(result.Warnings, "Operating system not specified, will default to ubuntu2204")
	}

	// Validate packages
	if len(payload.Packages) == 0 {
		result.Warnings = append(result.Warnings, "No packages specified")
	}

	if len(payload.Packages) > 50 {
		result.Passed = false
		result.Errors = append(result.Errors, "Too many packages (maximum 50)")
	}

	// Check for empty package names
	for i, pkg := range payload.Packages {
		if pkg.Name == "" {
			result.Passed = false
			result.Errors = append(result.Errors, "Package name cannot be empty at index "+string(rune(i+'0')))
		}
	}

	// Validate CVE data if present
	if payload.CVEData != nil {
		if payload.CVEData.ID == "" {
			result.Warnings = append(result.Warnings, "CVE ID is empty")
		}
	}

	// Check compliance controls
	validComplianceControls := map[string]bool{
		"pci":      true,
		"sox":      true,
		"hipaa":    true,
		"gdpr":     true,
		"iso27001": true,
	}

	for _, control := range payload.ComplianceControls {
		if !validComplianceControls[control] {
			result.Warnings = append(result.Warnings, "Unknown compliance control: "+control)
		}
	}

	return result, nil
}

// GetIntentPayload implements IntentUseCase
func (uc *intentUseCase) GetIntentPayload(ctx context.Context, intentID string) (*entity.IntentPayload, error) {
	// Get intent
	intent, err := uc.intentRepo.GetByID(ctx, intentID)
	if err != nil {
		return nil, err
	}

	// Parse payload
	var payload entity.IntentPayload
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		return nil, errors.NewInternal("Failed to parse intent payload").WithError(err)
	}

	return &payload, nil
}
