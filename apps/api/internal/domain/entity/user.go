package entity

import (
    "time"
)

// User represents a domain user entity
type User struct {
    ID        string    `gorm:"type:uuid;primary_key;default:gen_random_uuid()" json:"id"`
    ClerkID   string    `gorm:"type:varchar(255);uniqueIndex;not null" json:"clerk_id"`
    Email     string    `gorm:"type:varchar(255);uniqueIndex;not null" json:"email"`
    FirstName string    `gorm:"type:varchar(255)" json:"first_name"`
    LastName  string    `gorm:"type:varchar(255)" json:"last_name"`
    AvatarURL string    `gorm:"type:text" json:"avatar_url"`
    Role      string    `gorm:"type:varchar(50);default:'user';not null" json:"role"`
    CreatedAt time.Time `gorm:"autoCreateTime" json:"created_at"`
    UpdatedAt time.Time `gorm:"autoUpdateTime" json:"updated_at"`
}

// TableName specifies the table name for GORM
func (User) TableName() string {
    return "users"
}

// FullName returns the user's full name
func (u *User) FullName() string {
    if u.FirstName == "" && u.LastName == "" {
        return u.Email
    }
    if u.FirstName == "" {
        return u.LastName
    }
    if u.LastName == "" {
        return u.FirstName
    }
    return u.FirstName + " " + u.LastName
}

// Validate validates the user entity
func (u *User) Validate() error {
    if u.ClerkID == "" {
        return NewValidationError("clerk_id", "Clerk ID is required")
    }
    if u.Email == "" {
        return NewValidationError("email", "Email is required")
    }
    return nil
}

// ValidationError represents a validation error
type ValidationError struct {
    Field   string
    Message string
}

// NewValidationError creates a new validation error
func NewValidationError(field, message string) *ValidationError {
    return &ValidationError{
        Field:   field,
        Message: message,
    }
}

// Error implements the error interface
func (e *ValidationError) Error() string {
    return e.Message
}