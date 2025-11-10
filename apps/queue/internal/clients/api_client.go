package clients

import (
	"context"
	"fmt"

	"github.com/zerozero/apps/queue/pkg/logger"
	labsv1 "github.com/zerozero/proto/gen/go/labs/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// APIClient wraps the gRPC client for apps/api LabsService
// Used by Temporal activities to perform mutations
type APIClient struct {
	labsClient labsv1.LabsServiceClient
	conn       *grpc.ClientConn
	log        logger.Logger
}

// NewAPIClient creates a new API gRPC client
func NewAPIClient(address string, log logger.Logger) (*APIClient, error) {
	// Create gRPC connection (insecure for local development)
	// TODO: Add TLS support for production
	conn, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Error("failed to create API gRPC client", logger.String("address", address), logger.Error(err))
		return nil, fmt.Errorf("failed to dial API gRPC: %w", err)
	}

	log.Info("API gRPC client created", logger.String("address", address))

	return &APIClient{
		labsClient: labsv1.NewLabsServiceClient(conn),
		conn:       conn,
		log:        log,
	}, nil
}

// Close closes the gRPC connection
func (c *APIClient) Close() error {
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// UpdateLabStatus updates the status of a lab
func (c *APIClient) UpdateLabStatus(ctx context.Context, labID, status string, notes *string) error {
	req := &labsv1.UpdateLabStatusRequest{
		LabId:  labID,
		Status: status,
		Notes:  notes,
	}

	resp, err := c.labsClient.UpdateLabStatus(ctx, req)
	if err != nil {
		c.log.Error("failed to update lab status via gRPC",
			logger.String("lab_id", labID),
			logger.String("status", status),
			logger.Error(err))
		return fmt.Errorf("failed to update lab status: %w", err)
	}

	if !resp.Success {
		return fmt.Errorf("update lab status returned success=false")
	}

	c.log.Info("lab status updated via gRPC",
		logger.String("lab_id", labID),
		logger.String("status", status))

	return nil
}

// UpdateLabWorkflowIDs updates the workflow ID and run ID for a lab
func (c *APIClient) UpdateLabWorkflowIDs(ctx context.Context, labID, workflowID, runID string) error {
	req := &labsv1.UpdateLabWorkflowIDsRequest{
		LabId:      labID,
		WorkflowId: workflowID,
		RunId:      runID,
	}

	resp, err := c.labsClient.UpdateLabWorkflowIDs(ctx, req)
	if err != nil {
		c.log.Error("failed to update workflow IDs via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return fmt.Errorf("failed to update workflow IDs: %w", err)
	}

	if !resp.Success {
		return fmt.Errorf("update workflow IDs returned success=false")
	}

	return nil
}

// GenerateBlueprint calls the blueprint generation service via gRPC
func (c *APIClient) GenerateBlueprint(ctx context.Context, labID string) (*labsv1.Blueprint, error) {
	req := &labsv1.GenerateBlueprintRequest{
		LabId: labID,
	}

	resp, err := c.labsClient.GenerateBlueprint(ctx, req)
	if err != nil {
		c.log.Error("failed to generate blueprint via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return nil, fmt.Errorf("failed to generate blueprint: %w", err)
	}

	if !resp.Success {
		return nil, fmt.Errorf("generate blueprint returned success=false")
	}

	c.log.Info("blueprint generated via gRPC", logger.String("lab_id", labID))

	return resp.Blueprint, nil
}

// UpdateLabProvisioningDetails updates provisioning metadata for a lab
func (c *APIClient) UpdateLabProvisioningDetails(ctx context.Context, labID string, details map[string]interface{}) error {
	// Convert map to Struct protobuf
	// For now, we'll skip the complex conversion and just log
	// TODO: Implement proper Struct conversion

	c.log.Info("updating lab provisioning details via gRPC",
		logger.String("lab_id", labID))

	// Note: This would require converting the map to structpb.Struct
	// For placeholder purposes, we'll skip the actual call
	return nil
}

// GetLab retrieves lab details (read-only)
func (c *APIClient) GetLab(ctx context.Context, labID string) (*labsv1.Lab, error) {
	req := &labsv1.GetLabRequest{
		LabId: labID,
	}

	resp, err := c.labsClient.GetLab(ctx, req)
	if err != nil {
		c.log.Error("failed to get lab via gRPC",
			logger.String("lab_id", labID),
			logger.Error(err))
		return nil, fmt.Errorf("failed to get lab: %w", err)
	}

	return resp.Lab, nil
}
