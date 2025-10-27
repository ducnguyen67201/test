package entity

import (
    "time"
)

// User represents a domain user entity
type User struct {
    ID        string
    ClerkID   string
    Email     string
    FirstName string
    LastName  string
    AvatarURL string
    CreatedAt time.Time
    UpdatedAt time.Time
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