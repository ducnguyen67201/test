package grpc

import (
	"context"
	"encoding/json"

	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/internal/domain/repository"
	"github.com/zerozero/apps/api/internal/infrastructure/services"
	"github.com/zerozero/apps/api/internal/usecase"
	"github.com/zerozero/apps/api/pkg/errors"
	"github.com/zerozero/apps/api/pkg/logger"
	labsv1 "github.com/zerozero/proto/gen/go/labs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/structpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// LabsServiceGRPCServer implements the gRPC LabsService for internal mutations
// This is called by Temporal activities from apps/queue
type LabsServiceGRPCServer struct {
	labsv1.UnimplementedLabsServiceServer
	labUseCase       usecase.LabUseCase
	labRepo          repository.LabRepository
	blueprintService services.BlueprintService
	log              logger.Logger
}

// NewLabsServiceGRPCServer creates a new Labs gRPC service server
func NewLabsServiceGRPCServer(
	labUseCase usecase.LabUseCase,
	labRepo repository.LabRepository,
	blueprintService services.BlueprintService,
	logger logger.Logger,
) *LabsServiceGRPCServer {
	return &LabsServiceGRPCServer{
		labUseCase:       labUseCase,
		labRepo:          labRepo,
		blueprintService: blueprintService,
		log:              logger,
	}
}

// UpdateLabStatus updates the status of a lab (internal mutation from Temporal)
func (s *LabsServiceGRPCServer) UpdateLabStatus(
	ctx context.Context,
	req *labsv1.UpdateLabStatusRequest,
) (*labsv1.UpdateLabStatusResponse, error) {
	s.log.Info("gRPC: UpdateLabStatus",
		logger.String("lab_id", req.LabId),
		logger.String("status", req.Status))

	// Get lab from repository
	lab, err := s.labRepo.GetByID(ctx, req.LabId)
	if err != nil {
		s.log.Error("failed to get lab", logger.String("lab_id", req.LabId), logger.Error(err))
		return nil, status.Errorf(codes.NotFound, "lab not found: %s", req.LabId)
	}

	// Update status
	lab.Status = entity.LabStatus(req.Status)

	// Update in database
	lab, err = s.labRepo.Update(ctx, lab)
	if err != nil {
		s.log.Error("failed to update lab status",
			logger.String("lab_id", req.LabId),
			logger.Error(err))
		return nil, status.Errorf(codes.Internal, "failed to update lab status")
	}

	s.log.Info("lab status updated",
		logger.String("lab_id", req.LabId),
		logger.String("status", req.Status))

	return &labsv1.UpdateLabStatusResponse{
		Success: true,
		Lab:     s.entityToProto(lab),
	}, nil
}

// UpdateLabBlueprint updates the blueprint field after generation
func (s *LabsServiceGRPCServer) UpdateLabBlueprint(
	ctx context.Context,
	req *labsv1.UpdateLabBlueprintRequest,
) (*labsv1.UpdateLabBlueprintResponse, error) {
	s.log.Info("gRPC: UpdateLabBlueprint", logger.String("lab_id", req.LabId))

	// Get lab
	lab, err := s.labRepo.GetByID(ctx, req.LabId)
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "lab not found: %s", req.LabId)
	}

	// Convert proto blueprint to JSON
	blueprintBytes, err := json.Marshal(req.Blueprint)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to marshal blueprint")
	}
	lab.Blueprint = json.RawMessage(blueprintBytes)

	// Update in database
	lab, err = s.labRepo.Update(ctx, lab)
	if err != nil {
		s.log.Error("failed to update blueprint", logger.Error(err))
		return nil, status.Errorf(codes.Internal, "failed to update blueprint")
	}

	return &labsv1.UpdateLabBlueprintResponse{
		Success: true,
		Lab:     s.entityToProto(lab),
	}, nil
}

// UpdateLabWorkflowIDs stores the Temporal workflow ID and run ID
func (s *LabsServiceGRPCServer) UpdateLabWorkflowIDs(
	ctx context.Context,
	req *labsv1.UpdateLabWorkflowIDsRequest,
) (*labsv1.UpdateLabWorkflowIDsResponse, error) {
	s.log.Info("gRPC: UpdateLabWorkflowIDs",
		logger.String("lab_id", req.LabId),
		logger.String("workflow_id", req.WorkflowId))

	// Get lab
	lab, err := s.labRepo.GetByID(ctx, req.LabId)
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "lab not found: %s", req.LabId)
	}

	// Update workflow IDs
	lab.WorkflowID = &req.WorkflowId
	lab.RunID = &req.RunId

	// Update in database
	lab, err = s.labRepo.Update(ctx, lab)
	if err != nil {
		s.log.Error("failed to update workflow IDs", logger.Error(err))
		return nil, status.Errorf(codes.Internal, "failed to update workflow IDs")
	}

	return &labsv1.UpdateLabWorkflowIDsResponse{
		Success: true,
		Lab:     s.entityToProto(lab),
	}, nil
}

// UpdateLabProvisioningDetails updates provisioning metadata
func (s *LabsServiceGRPCServer) UpdateLabProvisioningDetails(
	ctx context.Context,
	req *labsv1.UpdateLabProvisioningDetailsRequest,
) (*labsv1.UpdateLabProvisioningDetailsResponse, error) {
	s.log.Info("gRPC: UpdateLabProvisioningDetails", logger.String("lab_id", req.LabId))

	// Get lab
	lab, err := s.labRepo.GetByID(ctx, req.LabId)
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "lab not found: %s", req.LabId)
	}

	// Convert struct to JSON
	detailsBytes, err := req.Details.MarshalJSON()
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to marshal details")
	}

	// Store as JSON (you may need to add a ProvisioningDetails field to lab entity)
	// For now, we'll assume it's part of the blueprint or separate field
	lab.Blueprint = json.RawMessage(detailsBytes)

	// Update in database
	lab, err = s.labRepo.Update(ctx, lab)
	if err != nil {
		s.log.Error("failed to update provisioning details", logger.Error(err))
		return nil, status.Errorf(codes.Internal, "failed to update provisioning details")
	}

	return &labsv1.UpdateLabProvisioningDetailsResponse{
		Success: true,
		Lab:     s.entityToProto(lab),
	}, nil
}

// GenerateBlueprint triggers blueprint generation for a lab
func (s *LabsServiceGRPCServer) GenerateBlueprint(
	ctx context.Context,
	req *labsv1.GenerateBlueprintRequest,
) (*labsv1.GenerateBlueprintResponse, error) {
	s.log.Info("gRPC: GenerateBlueprint", logger.String("lab_id", req.LabId))

	// Get lab
	lab, err := s.labRepo.GetByID(ctx, req.LabId)
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "lab not found: %s", req.LabId)
	}

	// Generate blueprint using the service
	blueprint, err := s.blueprintService.GenerateBlueprint(ctx, lab)
	if err != nil {
		s.log.Error("failed to generate blueprint", logger.Error(err))
		return nil, status.Errorf(codes.Internal, "failed to generate blueprint")
	}

	// Serialize RiskBadge to JSON string
	riskBadgeBytes, err := json.Marshal(blueprint.RiskBadge)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to marshal risk badge")
	}

	// Convert entity blueprint to proto
	protoBlueprint := &labsv1.Blueprint{
		Summary:   blueprint.Summary,
		RiskBadge: string(riskBadgeBytes),
		// Note: You may need to convert EnvironmentPlan, ValidationSteps, AutomationHooks
		// For now, returning basic fields
	}

	return &labsv1.GenerateBlueprintResponse{
		Success:   true,
		Blueprint: protoBlueprint,
	}, nil
}

// GetLab retrieves lab details (read-only for activities)
func (s *LabsServiceGRPCServer) GetLab(
	ctx context.Context,
	req *labsv1.GetLabRequest,
) (*labsv1.GetLabResponse, error) {
	s.log.Info("gRPC: GetLab", logger.String("lab_id", req.LabId))

	// Get lab
	lab, err := s.labRepo.GetByID(ctx, req.LabId)
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "lab not found: %s", req.LabId)
	}

	return &labsv1.GetLabResponse{
		Lab: s.entityToProto(lab),
	}, nil
}

// entityToProto converts a lab entity to proto
func (s *LabsServiceGRPCServer) entityToProto(lab *entity.LabRequest) *labsv1.Lab {
	protoLab := &labsv1.Lab{
		Id:        lab.ID,
		UserId:    lab.UserID,
		CveId:     lab.CVEID,
		Severity:  string(lab.Severity),
		Status:    string(lab.Status),
		TtlHours:  int32(lab.TTLHours),
		CreatedAt: timestamppb.New(lab.CreatedAt),
		UpdatedAt: timestamppb.New(lab.UpdatedAt),
	}

	// Add workflow IDs if present
	if lab.WorkflowID != nil {
		protoLab.WorkflowId = lab.WorkflowID
	}
	if lab.RunID != nil {
		protoLab.RunId = lab.RunID
	}

	// Add expires_at if present
	if lab.ExpiresAt != nil {
		protoLab.ExpiresAt = timestamppb.New(*lab.ExpiresAt)
	}

	// Convert blueprint JSON to Struct
	if lab.Blueprint != nil {
		var blueprintMap map[string]interface{}
		if err := json.Unmarshal(lab.Blueprint, &blueprintMap); err == nil {
			if blueprintStruct, err := structpb.NewStruct(blueprintMap); err == nil {
				protoLab.Blueprint = blueprintStruct
			}
		}
	}

	// Convert guardrail snapshot JSON to Struct
	if lab.GuardrailSnapshot != nil {
		var guardrailMap map[string]interface{}
		if err := json.Unmarshal(lab.GuardrailSnapshot, &guardrailMap); err == nil {
			if guardrailStruct, err := structpb.NewStruct(guardrailMap); err == nil {
				protoLab.GuardrailSnapshot = guardrailStruct
			}
		}
	}

	return protoLab
}

// handleError converts domain errors to gRPC errors
func (s *LabsServiceGRPCServer) handleError(err error) error {
	if appErr, ok := err.(*errors.AppError); ok {
		switch appErr.Code {
		case errors.ErrNotFound:
			return status.Error(codes.NotFound, err.Error())
		case errors.ErrUnauthorized:
			return status.Error(codes.Unauthenticated, err.Error())
		case errors.ErrForbidden:
			return status.Error(codes.PermissionDenied, err.Error())
		case errors.ErrValidation, errors.ErrBadRequest:
			return status.Error(codes.InvalidArgument, err.Error())
		case errors.ErrConflict:
			return status.Error(codes.AlreadyExists, err.Error())
		default:
			return status.Error(codes.Internal, err.Error())
		}
	}

	return status.Error(codes.Internal, err.Error())
}
