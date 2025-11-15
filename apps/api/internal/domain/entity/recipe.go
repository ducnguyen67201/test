package entity

import (
	"encoding/json"
	"time"
)

// Recipe represents a reusable environment template with software requirements
type Recipe struct {
	ID                   string          `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
	IntentID             *string         `gorm:"type:uuid;index" json:"intent_id,omitempty"`
	Name                 string          `gorm:"type:varchar(500);not null" json:"name"`
	Description          string          `gorm:"type:text" json:"description"`
	Software             string          `gorm:"type:varchar(200);not null;index" json:"software"`
	VersionConstraint    string          `gorm:"type:varchar(100)" json:"version_constraint"`
	OS                   string          `gorm:"type:varchar(100);not null;default:'ubuntu2204';index" json:"os"`
	Packages             json.RawMessage `gorm:"type:jsonb;not null;default:'[]'" json:"packages"`
	NetworkRequirements  string          `gorm:"type:text" json:"network_requirements,omitempty"`
	ComplianceControls   json.RawMessage `gorm:"type:jsonb;default:'[]'" json:"compliance_controls,omitempty"`
	ValidationChecks     json.RawMessage `gorm:"type:jsonb;default:'[]'" json:"validation_checks,omitempty"`
	CVEData              json.RawMessage `gorm:"type:jsonb" json:"cve_data,omitempty"`
	SourceURLs           json.RawMessage `gorm:"type:jsonb;default:'[]'" json:"source_urls,omitempty"`
	IsActive             bool            `gorm:"not null;default:true;index" json:"is_active"`
	CreatedBy            string          `gorm:"type:uuid;not null;index" json:"created_by"`
	CreatedAt            time.Time       `gorm:"autoCreateTime;index" json:"created_at"`
	UpdatedAt            time.Time       `gorm:"autoUpdateTime" json:"updated_at"`
}

// TableName specifies the table name for GORM
func (Recipe) TableName() string {
	return "recipes"
}

// RecipePackage represents a software package in a recipe
type RecipePackage struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	Source  string `json:"source,omitempty"`
}

// Validate validates the recipe entity
func (r *Recipe) Validate() error {
	if r.Name == "" {
		return NewValidationError("name", "Name is required")
	}
	if r.Software == "" {
		return NewValidationError("software", "Software is required")
	}
	if r.OS == "" {
		return NewValidationError("os", "OS is required")
	}
	if r.CreatedBy == "" {
		return NewValidationError("created_by", "CreatedBy is required")
	}
	return nil
}

// Activate activates the recipe for use
func (r *Recipe) Activate() {
	r.IsActive = true
}

// Deactivate deactivates the recipe
func (r *Recipe) Deactivate() {
	r.IsActive = false
}

// GetPackages unmarshals and returns the packages from JSONB
func (r *Recipe) GetPackages() ([]RecipePackage, error) {
	var packages []RecipePackage
	if len(r.Packages) == 0 {
		return packages, nil
	}
	err := json.Unmarshal(r.Packages, &packages)
	return packages, err
}

// SetPackages marshals and sets the packages to JSONB
func (r *Recipe) SetPackages(packages []RecipePackage) error {
	data, err := json.Marshal(packages)
	if err != nil {
		return err
	}
	r.Packages = data
	return nil
}

// GetComplianceControls unmarshals and returns compliance controls
func (r *Recipe) GetComplianceControls() ([]string, error) {
	var controls []string
	if len(r.ComplianceControls) == 0 {
		return controls, nil
	}
	err := json.Unmarshal(r.ComplianceControls, &controls)
	return controls, err
}

// SetComplianceControls marshals and sets compliance controls
func (r *Recipe) SetComplianceControls(controls []string) error {
	data, err := json.Marshal(controls)
	if err != nil {
		return err
	}
	r.ComplianceControls = data
	return nil
}

// GetValidationChecks unmarshals and returns validation checks
func (r *Recipe) GetValidationChecks() ([]string, error) {
	var checks []string
	if len(r.ValidationChecks) == 0 {
		return checks, nil
	}
	err := json.Unmarshal(r.ValidationChecks, &checks)
	return checks, err
}

// SetValidationChecks marshals and sets validation checks
func (r *Recipe) SetValidationChecks(checks []string) error {
	data, err := json.Marshal(checks)
	if err != nil {
		return err
	}
	r.ValidationChecks = data
	return nil
}

// GetCVEData unmarshals and returns CVE data
func (r *Recipe) GetCVEData() (*CVEData, error) {
	if len(r.CVEData) == 0 {
		return nil, nil
	}
	var cveData CVEData
	err := json.Unmarshal(r.CVEData, &cveData)
	return &cveData, err
}

// SetCVEData marshals and sets CVE data
func (r *Recipe) SetCVEData(cveData *CVEData) error {
	if cveData == nil {
		r.CVEData = nil
		return nil
	}
	data, err := json.Marshal(cveData)
	if err != nil {
		return err
	}
	r.CVEData = data
	return nil
}

// GetSourceURLs unmarshals and returns source URLs
func (r *Recipe) GetSourceURLs() ([]string, error) {
	var urls []string
	if len(r.SourceURLs) == 0 {
		return urls, nil
	}
	err := json.Unmarshal(r.SourceURLs, &urls)
	return urls, err
}

// SetSourceURLs marshals and sets source URLs
func (r *Recipe) SetSourceURLs(urls []string) error {
	data, err := json.Marshal(urls)
	if err != nil {
		return err
	}
	r.SourceURLs = data
	return nil
}
