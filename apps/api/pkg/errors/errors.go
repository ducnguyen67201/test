package errors

import (
    "fmt"
    "net/http"
)

// ErrorCode represents the type of error
type ErrorCode string

const (
    // Client errors
    ErrBadRequest          ErrorCode = "BAD_REQUEST"
    ErrUnauthorized        ErrorCode = "UNAUTHORIZED"
    ErrForbidden           ErrorCode = "FORBIDDEN"
    ErrNotFound            ErrorCode = "NOT_FOUND"
    ErrConflict            ErrorCode = "CONFLICT"
    ErrValidation          ErrorCode = "VALIDATION_ERROR"
    ErrRateLimited         ErrorCode = "RATE_LIMITED"

    // Server errors
    ErrInternal            ErrorCode = "INTERNAL_ERROR"
    ErrDatabaseError       ErrorCode = "DATABASE_ERROR"
    ErrCacheError          ErrorCode = "CACHE_ERROR"
    ErrExternalService     ErrorCode = "EXTERNAL_SERVICE_ERROR"
    ErrTimeout             ErrorCode = "TIMEOUT"
    ErrServiceUnavailable  ErrorCode = "SERVICE_UNAVAILABLE"
)

// AppError represents an application error
type AppError struct {
    Code       ErrorCode              `json:"code"`
    Message    string                 `json:"message"`
    Details    string                 `json:"details,omitempty"`
    Metadata   map[string]interface{} `json:"metadata,omitempty"`
    StatusCode int                    `json:"-"`
    Err        error                  `json:"-"`
}

// Error implements the error interface
func (e *AppError) Error() string {
    if e.Err != nil {
        return fmt.Sprintf("%s: %s - %v", e.Code, e.Message, e.Err)
    }
    return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

// Unwrap returns the wrapped error
func (e *AppError) Unwrap() error {
    return e.Err
}

// WithError adds an underlying error
func (e *AppError) WithError(err error) *AppError {
    e.Err = err
    return e
}

// WithDetails adds details to the error
func (e *AppError) WithDetails(details string) *AppError {
    e.Details = details
    return e
}

// WithMetadata adds metadata to the error
func (e *AppError) WithMetadata(key string, value interface{}) *AppError {
    if e.Metadata == nil {
        e.Metadata = make(map[string]interface{})
    }
    e.Metadata[key] = value
    return e
}

// Constructor functions for common errors

// NewBadRequest creates a bad request error
func NewBadRequest(message string) *AppError {
    return &AppError{
        Code:       ErrBadRequest,
        Message:    message,
        StatusCode: http.StatusBadRequest,
    }
}

// NewUnauthorized creates an unauthorized error
func NewUnauthorized(message string) *AppError {
    return &AppError{
        Code:       ErrUnauthorized,
        Message:    message,
        StatusCode: http.StatusUnauthorized,
    }
}

// NewForbidden creates a forbidden error
func NewForbidden(message string) *AppError {
    return &AppError{
        Code:       ErrForbidden,
        Message:    message,
        StatusCode: http.StatusForbidden,
    }
}

// NewNotFound creates a not found error
func NewNotFound(resource string) *AppError {
    return &AppError{
        Code:       ErrNotFound,
        Message:    fmt.Sprintf("%s not found", resource),
        StatusCode: http.StatusNotFound,
    }
}

// NewConflict creates a conflict error
func NewConflict(message string) *AppError {
    return &AppError{
        Code:       ErrConflict,
        Message:    message,
        StatusCode: http.StatusConflict,
    }
}

// NewValidation creates a validation error
func NewValidation(message string) *AppError {
    return &AppError{
        Code:       ErrValidation,
        Message:    message,
        StatusCode: http.StatusBadRequest,
    }
}

// NewInternal creates an internal server error
func NewInternal(message string) *AppError {
    return &AppError{
        Code:       ErrInternal,
        Message:    message,
        StatusCode: http.StatusInternalServerError,
    }
}

// NewDatabaseError creates a database error
func NewDatabaseError(message string) *AppError {
    return &AppError{
        Code:       ErrDatabaseError,
        Message:    message,
        StatusCode: http.StatusInternalServerError,
    }
}

// IsNotFound checks if error is a not found error
func IsNotFound(err error) bool {
    if appErr, ok := err.(*AppError); ok {
        return appErr.Code == ErrNotFound
    }
    return false
}

// IsUnauthorized checks if error is an unauthorized error
func IsUnauthorized(err error) bool {
    if appErr, ok := err.(*AppError); ok {
        return appErr.Code == ErrUnauthorized
    }
    return false
}

// IsValidation checks if error is a validation error
func IsValidation(err error) bool {
    if appErr, ok := err.(*AppError); ok {
        return appErr.Code == ErrValidation
    }
    return false
}