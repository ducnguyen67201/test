package services

import (
	"context"
	"fmt"
	"strings"

	"github.com/zerozero/apps/api/pkg/logger"
)

// ValidatorService defines the interface for validation and guardrail operations
type ValidatorService interface {
	// ValidatePackage validates a package against allowed/banned lists
	ValidatePackage(ctx context.Context, packageName string, version string) (*PackageValidationResult, error)

	// ValidateOS validates an operating system against supported list
	ValidateOS(ctx context.Context, os string) (*OSValidationResult, error)

	// ValidateSoftware validates software against allowed list
	ValidateSoftware(ctx context.Context, software string) (*SoftwareValidationResult, error)

	// ValidateCompliance validates compliance controls
	ValidateCompliance(ctx context.Context, controls []string) (*ComplianceValidationResult, error)

	// CheckBannedCVE checks if a CVE is banned
	CheckBannedCVE(ctx context.Context, cveID string) (bool, string, error)
}

// PackageValidationResult contains package validation results
type PackageValidationResult struct {
	Allowed bool   `json:"allowed"`
	Reason  string `json:"reason,omitempty"`
}

// OSValidationResult contains OS validation results
type OSValidationResult struct {
	Supported bool   `json:"supported"`
	Reason    string `json:"reason,omitempty"`
}

// SoftwareValidationResult contains software validation results
type SoftwareValidationResult struct {
	Allowed bool   `json:"allowed"`
	Reason  string `json:"reason,omitempty"`
}

// ComplianceValidationResult contains compliance validation results
type ComplianceValidationResult struct {
	Valid    bool     `json:"valid"`
	Unknown  []string `json:"unknown,omitempty"`
	Warnings []string `json:"warnings,omitempty"`
}

// DefaultValidatorService is the default implementation of ValidatorService
type DefaultValidatorService struct {
	supportedOS          map[string]bool
	bannedPackages       map[string]bool
	bannedCVEs           map[string]string
	validCompliance      map[string]bool
	log                  logger.Logger
}

// NewDefaultValidatorService creates a new default validator service
func NewDefaultValidatorService(log logger.Logger) ValidatorService {
	return &DefaultValidatorService{
		supportedOS: map[string]bool{
			"ubuntu2204": true,
			"ubuntu2004": true,
			"ubuntu2404": true,
			"debian12":   true,
			"debian11":   true,
			"alpine3.18": true,
			"alpine3.19": true,
		},
		bannedPackages: map[string]bool{
			// Add banned packages here (e.g., known malware)
			"malicious-package": true,
		},
		bannedCVEs: map[string]string{
			// Add banned CVEs here with reasons
			// "CVE-2024-XXXX": "Critical vulnerability, no safe usage",
		},
		validCompliance: map[string]bool{
			"pci":      true,
			"sox":      true,
			"hipaa":    true,
			"gdpr":     true,
			"iso27001": true,
			"fedramp":  true,
			"nist":     true,
		},
		log: log,
	}
}

// ValidatePackage implements ValidatorService
func (v *DefaultValidatorService) ValidatePackage(ctx context.Context, packageName string, version string) (*PackageValidationResult, error) {
	// Check if package is banned
	if v.bannedPackages[strings.ToLower(packageName)] {
		return &PackageValidationResult{
			Allowed: false,
			Reason:  fmt.Sprintf("Package '%s' is not allowed", packageName),
		}, nil
	}

	// Check for suspicious patterns
	suspicious := []string{"malware", "backdoor", "exploit-kit", "ransomware"}
	lowerName := strings.ToLower(packageName)
	for _, pattern := range suspicious {
		if strings.Contains(lowerName, pattern) {
			v.log.Warn("Suspicious package name detected",
				logger.String("package", packageName))
			return &PackageValidationResult{
				Allowed: false,
				Reason:  fmt.Sprintf("Package name contains suspicious pattern: %s", pattern),
			}, nil
		}
	}

	// Package is allowed
	return &PackageValidationResult{
		Allowed: true,
	}, nil
}

// ValidateOS implements ValidatorService
func (v *DefaultValidatorService) ValidateOS(ctx context.Context, os string) (*OSValidationResult, error) {
	if v.supportedOS[strings.ToLower(os)] {
		return &OSValidationResult{
			Supported: true,
		}, nil
	}

	return &OSValidationResult{
		Supported: false,
		Reason:    fmt.Sprintf("OS '%s' is not supported. Supported OS: ubuntu2204, ubuntu2004, debian12, debian11, alpine3.18, alpine3.19", os),
	}, nil
}

// ValidateSoftware implements ValidatorService
func (v *DefaultValidatorService) ValidateSoftware(ctx context.Context, software string) (*SoftwareValidationResult, error) {
	// For now, allow all software
	// In production, you might want to maintain an allowed/banned list

	// Check for suspicious patterns
	suspicious := []string{"malware", "backdoor", "trojan"}
	lowerSoftware := strings.ToLower(software)
	for _, pattern := range suspicious {
		if strings.Contains(lowerSoftware, pattern) {
			v.log.Warn("Suspicious software name detected",
				logger.String("software", software))
			return &SoftwareValidationResult{
				Allowed: false,
				Reason:  fmt.Sprintf("Software name contains suspicious pattern: %s", pattern),
			}, nil
		}
	}

	return &SoftwareValidationResult{
		Allowed: true,
	}, nil
}

// ValidateCompliance implements ValidatorService
func (v *DefaultValidatorService) ValidateCompliance(ctx context.Context, controls []string) (*ComplianceValidationResult, error) {
	result := &ComplianceValidationResult{
		Valid:    true,
		Unknown:  []string{},
		Warnings: []string{},
	}

	for _, control := range controls {
		lowerControl := strings.ToLower(control)
		if !v.validCompliance[lowerControl] {
			result.Unknown = append(result.Unknown, control)
			result.Warnings = append(result.Warnings, fmt.Sprintf("Unknown compliance control: %s", control))
		}
	}

	// Don't fail validation for unknown controls, just warn
	return result, nil
}

// CheckBannedCVE implements ValidatorService
func (v *DefaultValidatorService) CheckBannedCVE(ctx context.Context, cveID string) (bool, string, error) {
	if reason, banned := v.bannedCVEs[strings.ToUpper(cveID)]; banned {
		return true, reason, nil
	}
	return false, "", nil
}
