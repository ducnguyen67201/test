package services

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/zerozero/apps/api/internal/domain/entity"
	"github.com/zerozero/apps/api/pkg/logger"
)

// BlueprintService defines the interface for blueprint generation
type BlueprintService interface {
	GenerateBlueprint(ctx context.Context, request *entity.LabRequest) (*entity.Blueprint, error)
}

// MockBlueprintService is a mock implementation for MVP
// This can be replaced with a real LLM integration later
type MockBlueprintService struct {
	log logger.Logger
}

// NewMockBlueprintService creates a new mock blueprint service
func NewMockBlueprintService(log logger.Logger) BlueprintService {
	return &MockBlueprintService{
		log: log,
	}
}

// GenerateBlueprint generates a mock blueprint based on the request
func (s *MockBlueprintService) GenerateBlueprint(ctx context.Context, request *entity.LabRequest) (*entity.Blueprint, error) {
	s.log.Info("Generating mock blueprint",
		logger.String("lab_id", request.ID),
		logger.String("cve_id", request.CVEID),
		logger.String("severity", request.Severity.String()))

	// Generate mock blueprint based on severity
	blueprint := &entity.Blueprint{
		Summary:         s.generateSummary(request),
		RiskBadge:       s.generateRiskBadge(request),
		EnvironmentPlan: s.generateEnvironmentPlan(request),
		ValidationSteps: s.generateValidationSteps(request),
		AutomationHooks: s.generateAutomationHooks(request),
	}

	return blueprint, nil
}

func (s *MockBlueprintService) generateSummary(request *entity.LabRequest) string {
	if request.CVEID != "" {
		return fmt.Sprintf(
			"Lab environment for analyzing %s: %s. This %s severity vulnerability requires careful analysis within a controlled environment. The lab will be provisioned with necessary tools and configurations for safe exploitation testing.",
			request.CVEID,
			request.Title,
			request.Severity,
		)
	}
	return fmt.Sprintf(
		"Lab environment for analyzing: %s. This %s severity analysis will be conducted in an isolated environment with appropriate safeguards and monitoring.",
		request.Title,
		request.Severity,
	)
}

func (s *MockBlueprintService) generateRiskBadge(request *entity.LabRequest) entity.RiskBadge {
	var reason string
	switch request.Severity {
	case entity.LabSeverityCritical:
		reason = "Critical severity vulnerability with potential for remote code execution or complete system compromise. Requires strict isolation and monitoring."
	case entity.LabSeverityHigh:
		reason = "High severity vulnerability that could lead to significant security impact. Close monitoring and proper containment required."
	case entity.LabSeverityMedium:
		reason = "Medium severity vulnerability with moderate security implications. Standard lab safety protocols apply."
	case entity.LabSeverityLow:
		reason = "Low severity vulnerability with limited security impact. Routine analysis procedures apply."
	}

	return entity.RiskBadge{
		Level:  request.Severity,
		Reason: reason,
	}
}

func (s *MockBlueprintService) generateEnvironmentPlan(request *entity.LabRequest) entity.EnvironmentPlan {
	baseImage := "ubuntu:22.04"
	dependencies := []string{
		"curl",
		"wget",
		"nmap",
		"netcat",
		"python3",
		"python3-pip",
	}

	// Add specialized tools based on CVE or title keywords
	if request.CVEID != "" {
		cve := request.CVEID
		if contains(cve, "SQL") || contains(request.Title, "SQL") {
			dependencies = append(dependencies, "mysql-client", "postgresql-client", "sqlmap")
		}
		if contains(request.Title, "XSS") || contains(request.Title, "Cross-Site") {
			dependencies = append(dependencies, "chromium-browser", "firefox")
		}
		if contains(request.Title, "Docker") || contains(request.Title, "Container") {
			baseImage = "docker:dind"
			dependencies = append(dependencies, "docker-cli", "docker-compose")
		}
	}

	config := map[string]string{
		"network_isolation": "enabled",
		"internet_access":   "restricted",
		"monitoring":        "enabled",
		"logging":           "verbose",
	}

	// Stricter controls for higher severity
	if request.Severity == entity.LabSeverityCritical || request.Severity == entity.LabSeverityHigh {
		config["egress_filtering"] = "strict"
		config["file_integrity_monitoring"] = "enabled"
	}

	return entity.EnvironmentPlan{
		BaseImage:     baseImage,
		Dependencies:  dependencies,
		Configuration: config,
	}
}

func (s *MockBlueprintService) generateValidationSteps(request *entity.LabRequest) []string {
	steps := []string{
		"Verify environment isolation and network restrictions",
		"Confirm all required dependencies are installed",
		"Validate baseline system state and integrity",
	}

	switch request.Severity {
	case entity.LabSeverityCritical:
		steps = append(steps,
			"Deploy additional monitoring and alerting systems",
			"Establish secure communication channels",
			"Configure automated kill switches",
			"Verify exploit containment mechanisms",
			"Test incident response procedures",
		)
	case entity.LabSeverityHigh:
		steps = append(steps,
			"Configure enhanced logging and monitoring",
			"Set up containment boundaries",
			"Test rollback procedures",
		)
	case entity.LabSeverityMedium:
		steps = append(steps,
			"Enable standard logging",
			"Configure basic containment",
		)
	case entity.LabSeverityLow:
		steps = append(steps,
			"Enable routine logging",
		)
	}

	steps = append(steps,
		fmt.Sprintf("Verify lab will auto-terminate after %d hours", request.TTLHours),
		"Document initial state for post-analysis review",
	)

	return steps
}

func (s *MockBlueprintService) generateAutomationHooks(request *entity.LabRequest) []entity.AutomationHook {
	hooks := []entity.AutomationHook{
		{
			Name:    "Initialize Environment",
			Command: "/lab/scripts/init.sh",
			Stage:   "pre_start",
		},
		{
			Name:    "Baseline Snapshot",
			Command: "/lab/scripts/snapshot.sh create baseline",
			Stage:   "post_start",
		},
	}

	if request.Severity == entity.LabSeverityCritical || request.Severity == entity.LabSeverityHigh {
		hooks = append(hooks, entity.AutomationHook{
			Name:    "Enable Advanced Monitoring",
			Command: "/lab/scripts/monitor.sh --mode=advanced",
			Stage:   "post_start",
		})
	}

	hooks = append(hooks,
		entity.AutomationHook{
			Name:    "Collect Artifacts",
			Command: "/lab/scripts/collect-artifacts.sh",
			Stage:   "pre_stop",
		},
		entity.AutomationHook{
			Name:    "Final Snapshot",
			Command: "/lab/scripts/snapshot.sh create final",
			Stage:   "pre_stop",
		},
		entity.AutomationHook{
			Name:    "Cleanup",
			Command: "/lab/scripts/cleanup.sh",
			Stage:   "post_stop",
		},
	)

	return hooks
}

// Helper function to check if string contains substring (case insensitive)
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || jsonContains(s, substr))
}

func jsonContains(s, substr string) bool {
	// Simple case-insensitive contains check
	sLower := make([]byte, len(s))
	substrLower := make([]byte, len(substr))
	for i := range s {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			sLower[i] = c + 32
		} else {
			sLower[i] = c
		}
	}
	for i := range substr {
		c := substr[i]
		if c >= 'A' && c <= 'Z' {
			substrLower[i] = c + 32
		} else {
			substrLower[i] = c
		}
	}
	for i := 0; i <= len(sLower)-len(substrLower); i++ {
		match := true
		for j := range substrLower {
			if sLower[i+j] != substrLower[j] {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}

// SerializeBlueprint converts a blueprint to JSON for storage
func SerializeBlueprint(blueprint *entity.Blueprint) (json.RawMessage, error) {
	data, err := json.Marshal(blueprint)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize blueprint: %w", err)
	}
	return json.RawMessage(data), nil
}

// DeserializeBlueprint converts JSON to a blueprint
func DeserializeBlueprint(data json.RawMessage) (*entity.Blueprint, error) {
	var blueprint entity.Blueprint
	if err := json.Unmarshal(data, &blueprint); err != nil {
		return nil, fmt.Errorf("failed to deserialize blueprint: %w", err)
	}
	return &blueprint, nil
}
