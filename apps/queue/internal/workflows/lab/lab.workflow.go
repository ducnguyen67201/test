package lab

import (
	"fmt"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

// LabProvisionWorkflow orchestrates the lab provisioning process
// This workflow coordinates all steps from blueprint generation to final deployment
func LabProvisionWorkflow(ctx workflow.Context, params LabProvisionParams) (*LabProvisionResult, error) {
	logger := workflow.GetLogger(ctx)
	logger.Info("Starting lab provision workflow", "lab_id", params.LabID)

	// Set activity options with retries
	ao := workflow.ActivityOptions{
		StartToCloseTimeout: 10 * time.Minute,
		RetryPolicy: &temporal.RetryPolicy{
			InitialInterval:    1 * time.Second,
			BackoffCoefficient: 2.0,
			MaximumInterval:    1 * time.Minute,
			MaximumAttempts:    3,
		},
	}
	ctx = workflow.WithActivityOptions(ctx, ao)

	var a *Activities

	// Track current phase for queries
	var currentPhase string
	var percentComplete int

	// Register workflow queries
	err := workflow.SetQueryHandler(ctx, "current_phase", func() (string, error) {
		return currentPhase, nil
	})
	if err != nil {
		logger.Error("Failed to set current_phase query handler", "error", err)
	}

	err = workflow.SetQueryHandler(ctx, "percent_complete", func() (int, error) {
		return percentComplete, nil
	})
	if err != nil {
		logger.Error("Failed to set percent_complete query handler", "error", err)
	}

	// Register cancel signal
	cancelChannel := workflow.GetSignalChannel(ctx, "cancel-lab")
	cancelRequested := false

	workflow.Go(ctx, func(ctx workflow.Context) {
		cancelChannel.Receive(ctx, &cancelRequested)
		if cancelRequested {
			logger.Info("Cancel signal received", "lab_id", params.LabID)
		}
	})

	// Step 1: Lock lab (gRPC: UpdateLabStatus -> queued)
	currentPhase = "locking"
	percentComplete = 0
	logger.Info("Step 1: Locking lab", "lab_id", params.LabID)

	if err := workflow.ExecuteActivity(ctx, a.LockLab, params.LabID).Get(ctx, nil); err != nil {
		logger.Error("Failed to lock lab", "error", err)
		return nil, fmt.Errorf("failed to lock lab: %w", err)
	}

	if cancelRequested {
		return nil, fmt.Errorf("workflow cancelled during lock phase")
	}

	// Step 2: Generate blueprint (gRPC: GenerateBlueprint)
	currentPhase = "generating_blueprint"
	percentComplete = 20
	logger.Info("Step 2: Generating blueprint", "lab_id", params.LabID)

	var blueprint Blueprint
	if err := workflow.ExecuteActivity(ctx, a.GenerateBlueprint, params.LabID, params.CVEID).Get(ctx, &blueprint); err != nil {
		logger.Error("Failed to generate blueprint", "error", err)
		// Reject lab on failure
		workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Blueprint generation failed").Get(ctx, nil)
		return nil, fmt.Errorf("failed to generate blueprint: %w", err)
	}

	if cancelRequested {
		workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Cancelled during blueprint generation").Get(ctx, nil)
		return nil, fmt.Errorf("workflow cancelled during blueprint generation")
	}

	// Step 3: Provision environment (gRPC: ProvisionerService)
	currentPhase = "provisioning"
	percentComplete = 40
	logger.Info("Step 3: Provisioning environment", "lab_id", params.LabID)

	var provisionResult ProvisionResult
	if err := workflow.ExecuteActivity(ctx, a.ProvisionEnvironment, params.LabID, params.CVEID, blueprint).Get(ctx, &provisionResult); err != nil {
		logger.Error("Failed to provision environment", "error", err)
		workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Provisioning failed").Get(ctx, nil)
		return nil, fmt.Errorf("failed to provision: %w", err)
	}

	if cancelRequested {
		workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Cancelled during provisioning").Get(ctx, nil)
		return nil, fmt.Errorf("workflow cancelled during provisioning")
	}

	// Step 4: Run validation (gRPC: ValidateEnvironment)
	currentPhase = "validating"
	percentComplete = 60
	logger.Info("Step 4: Running validation", "lab_id", params.LabID)

	if err := workflow.ExecuteActivity(ctx, a.RunValidation, params.LabID, provisionResult.JobID).Get(ctx, nil); err != nil {
		logger.Error("Failed validation", "error", err)
		workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Validation failed").Get(ctx, nil)
		return nil, fmt.Errorf("failed validation: %w", err)
	}

	if cancelRequested {
		workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Cancelled during validation").Get(ctx, nil)
		return nil, fmt.Errorf("workflow cancelled during validation")
	}

	// Step 5: Human review (optional - signal wait)
	if params.RequiresReview {
		currentPhase = "awaiting_review"
		percentComplete = 80
		logger.Info("Step 5: Waiting for human review", "lab_id", params.LabID)

		var reviewResult ReviewResult
		signalChan := workflow.GetSignalChannel(ctx, "human-review")

		// Wait for review signal with timeout (24 hours)
		selector := workflow.NewSelector(ctx)
		reviewReceived := false

		selector.AddReceive(signalChan, func(c workflow.ReceiveChannel, more bool) {
			c.Receive(ctx, &reviewResult)
			reviewReceived = true
		})

		// Add timeout
		timer := workflow.NewTimer(ctx, 24*time.Hour)
		selector.AddFuture(timer, func(f workflow.Future) {
			logger.Warn("Review timeout reached", "lab_id", params.LabID)
		})

		selector.Select(ctx)

		if !reviewReceived {
			// Timeout reached
			workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, "Review timeout exceeded").Get(ctx, nil)
			return nil, fmt.Errorf("review timeout exceeded for lab %s", params.LabID)
		}

		if !reviewResult.Approved {
			workflow.ExecuteActivity(ctx, a.RejectLab, params.LabID, reviewResult.Notes).Get(ctx, nil)
			return nil, fmt.Errorf("lab rejected by reviewer: %s", reviewResult.Notes)
		}

		logger.Info("Lab approved by reviewer", "reviewed_by", reviewResult.ReviewedBy)
	}

	// Step 6: Finalize (gRPC: UpdateLabStatus -> running)
	currentPhase = "finalizing"
	percentComplete = 90
	logger.Info("Step 6: Finalizing lab", "lab_id", params.LabID)

	if err := workflow.ExecuteActivity(ctx, a.FinalizeLab, params.LabID).Get(ctx, nil); err != nil {
		logger.Error("Failed to finalize lab", "error", err)
		return nil, fmt.Errorf("failed to finalize: %w", err)
	}

	currentPhase = "completed"
	percentComplete = 100
	logger.Info("Lab provision workflow completed successfully", "lab_id", params.LabID)

	return &LabProvisionResult{
		Success: true,
		LabID:   params.LabID,
		Message: "Lab provisioned successfully",
	}, nil
}
