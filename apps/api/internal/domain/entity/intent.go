package entity

import (
	"encoding/json"
	"time"
)

// IntentStatus represents the approval status of an intent
type IntentStatus string

const (
	IntentStatusDraft    IntentStatus = "draft"
	IntentStatusApproved IntentStatus = "approved"
	IntentStatusRejected IntentStatus = "rejected"
)

// Intent represents extracted user intent from a chat session
type Intent struct {
	ID               string          `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
	SessionID        string          `gorm:"type:uuid;not null;uniqueIndex" json:"session_id"`
	Payload          json.RawMessage `gorm:"type:jsonb;not null" json:"payload"`
	Confidence       float64         `gorm:"type:decimal(3,2);not null" json:"confidence"`
	Status           IntentStatus    `gorm:"type:intent_status;not null;default:'draft';index" json:"status"`
	ValidatorErrors  json.RawMessage `gorm:"type:jsonb" json:"validator_errors,omitempty"`
	CreatedAt        time.Time       `gorm:"autoCreateTime;index" json:"created_at"`
	UpdatedAt        time.Time       `gorm:"autoUpdateTime" json:"updated_at"`
}

// TableName specifies the table name for GORM
func (Intent) TableName() string {
	return "intents"
}

// IntentPayload represents the structured intent extracted from chat
type IntentPayload struct {
	Name                  string                   `json:"name"`
	Description           string                   `json:"description"`
	Software              string                   `json:"software"`
	VersionConstraint     string                   `json:"version_constraint"`
	ExploitFamily         string                   `json:"exploit_family,omitempty"`
	IsActive              bool                     `json:"is_active"`
	OS                    string                   `json:"os"`
	Packages              []IntentPackage          `json:"packages"`
	NetworkRequirements   string                   `json:"network_requirements,omitempty"`
	ComplianceControls    []string                 `json:"compliance_controls,omitempty"`
	ValidationChecks      []string                 `json:"validation_checks,omitempty"`
	CVEData               *CVEData                 `json:"cve_data,omitempty"`
	SourceURLs            []string                 `json:"source_urls,omitempty"`
	Confidence            float64                  `json:"confidence"`
}

// IntentPackage represents a software package in the intent
type IntentPackage struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	Source  string `json:"source,omitempty"`
}

// CVEData represents CVE information fetched from the internet
type CVEData struct {
	ID                  string   `json:"id"`
	Title               string   `json:"title"`
	Description         string   `json:"description"`
	Severity            string   `json:"severity"`
	CVSSScore           float64  `json:"cvss_score,omitempty"`
	ExploitabilityScore float64  `json:"exploitability_score,omitempty"`
	PublishedDate       string   `json:"published_date,omitempty"` // Changed to string to handle various date formats
	AffectedVersions    []string `json:"affected_versions,omitempty"`
	References          []string `json:"references,omitempty"`
}

// Validate validates the intent entity
func (i *Intent) Validate() error {
	if i.SessionID == "" {
		return NewValidationError("session_id", "Session ID is required")
	}
	if len(i.Payload) == 0 {
		return NewValidationError("payload", "Payload is required")
	}
	if i.Confidence < 0 || i.Confidence > 1 {
		return NewValidationError("confidence", "Confidence must be between 0 and 1")
	}
	return nil
}

// IsApproved checks if the intent has been approved
func (i *Intent) IsApproved() bool {
	return i.Status == IntentStatusApproved
}

// IsRejected checks if the intent has been rejected
func (i *Intent) IsRejected() bool {
	return i.Status == IntentStatusRejected
}

// IsDraft checks if the intent is still in draft status
func (i *Intent) IsDraft() bool {
	return i.Status == IntentStatusDraft
}

// HasValidationErrors checks if there are validation errors
func (i *Intent) HasValidationErrors() bool {
	return len(i.ValidatorErrors) > 0
}

// MeetsConfidenceThreshold checks if confidence is above the minimum threshold
func (i *Intent) MeetsConfidenceThreshold(threshold float64) bool {
	return i.Confidence >= threshold
}

// Approve approves the intent
func (i *Intent) Approve() {
	i.Status = IntentStatusApproved
}

// Reject rejects the intent
func (i *Intent) Reject() {
	i.Status = IntentStatusRejected
}

// String implements the Stringer interface for IntentStatus
func (is IntentStatus) String() string {
	return string(is)
}
