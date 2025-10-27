package logger

import (
    "context"
    "fmt"
    "log"
    "os"
    "runtime"
    "strings"
    "time"
)

// Level represents the severity level of a log message
type Level int

const (
    DebugLevel Level = iota
    InfoLevel
    WarnLevel
    ErrorLevel
    FatalLevel
)

// Logger interface defines the logging contract
type Logger interface {
    Debug(msg string, fields ...Field)
    Info(msg string, fields ...Field)
    Warn(msg string, fields ...Field)
    Error(msg string, fields ...Field)
    Fatal(msg string, fields ...Field)
    WithContext(ctx context.Context) Logger
    WithFields(fields ...Field) Logger
}

// Field represents a key-value pair for structured logging
type Field struct {
    Key   string
    Value interface{}
}

// logger is the default implementation
type logger struct {
    level  Level
    fields []Field
    ctx    context.Context
}

// New creates a new logger instance
func New(level string) Logger {
    var logLevel Level
    switch strings.ToLower(level) {
    case "debug":
        logLevel = DebugLevel
    case "info":
        logLevel = InfoLevel
    case "warn":
        logLevel = WarnLevel
    case "error":
        logLevel = ErrorLevel
    case "fatal":
        logLevel = FatalLevel
    default:
        logLevel = InfoLevel
    }

    return &logger{
        level:  logLevel,
        fields: []Field{},
        ctx:    context.Background(),
    }
}

// WithContext creates a new logger with context
func (l *logger) WithContext(ctx context.Context) Logger {
    return &logger{
        level:  l.level,
        fields: l.fields,
        ctx:    ctx,
    }
}

// WithFields creates a new logger with additional fields
func (l *logger) WithFields(fields ...Field) Logger {
    newFields := make([]Field, len(l.fields)+len(fields))
    copy(newFields, l.fields)
    copy(newFields[len(l.fields):], fields)

    return &logger{
        level:  l.level,
        fields: newFields,
        ctx:    l.ctx,
    }
}

// Debug logs a debug message
func (l *logger) Debug(msg string, fields ...Field) {
    if l.level <= DebugLevel {
        l.log("DEBUG", msg, fields...)
    }
}

// Info logs an info message
func (l *logger) Info(msg string, fields ...Field) {
    if l.level <= InfoLevel {
        l.log("INFO", msg, fields...)
    }
}

// Warn logs a warning message
func (l *logger) Warn(msg string, fields ...Field) {
    if l.level <= WarnLevel {
        l.log("WARN", msg, fields...)
    }
}

// Error logs an error message
func (l *logger) Error(msg string, fields ...Field) {
    if l.level <= ErrorLevel {
        l.log("ERROR", msg, fields...)
    }
}

// Fatal logs a fatal message and exits
func (l *logger) Fatal(msg string, fields ...Field) {
    l.log("FATAL", msg, fields...)
    os.Exit(1)
}

// log is the internal logging function
func (l *logger) log(level, msg string, fields ...Field) {
    // Get caller information
    _, file, line, _ := runtime.Caller(2)
    parts := strings.Split(file, "/")
    file = parts[len(parts)-1]

    // Build log entry
    timestamp := time.Now().Format("2006-01-02 15:04:05.000")
    entry := fmt.Sprintf("[%s] %s %s:%d - %s", timestamp, level, file, line, msg)

    // Add fields
    allFields := append(l.fields, fields...)
    if len(allFields) > 0 {
        fieldStrs := make([]string, len(allFields))
        for i, field := range allFields {
            fieldStrs[i] = fmt.Sprintf("%s=%v", field.Key, field.Value)
        }
        entry += " | " + strings.Join(fieldStrs, " ")
    }

    // Output
    if level == "ERROR" || level == "FATAL" {
        log.Println(entry)
    } else {
        log.Println(entry)
    }
}

// Helper functions for creating fields
func String(key, value string) Field {
    return Field{Key: key, Value: value}
}

func Int(key string, value int) Field {
    return Field{Key: key, Value: value}
}

func Error(err error) Field {
    return Field{Key: "error", Value: err.Error()}
}

func Any(key string, value interface{}) Field {
    return Field{Key: key, Value: value}
}