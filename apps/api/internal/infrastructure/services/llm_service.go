package services

import (
	"context"
	"github.com/zerozero/apps/api/pkg/llm"
)

// LLMService defines the interface for LLM operations
type LLMService interface {
	// Chat sends a chat completion request and returns the response
	Chat(ctx context.Context, request *llm.CompletionRequest) (*llm.CompletionResponse, error)

	// StreamChat sends a chat completion request and streams the response via a channel
	StreamChat(ctx context.Context, request *llm.CompletionRequest) (<-chan llm.StreamDelta, <-chan error)

	// ExtractIntent extracts structured intent from conversation history
	ExtractIntent(ctx context.Context, request *llm.IntentExtractionRequest) (*llm.IntentExtractionResponse, error)

	// EstimateTokens estimates the number of tokens in a text
	EstimateTokens(text string) int

	// CountMessageTokens counts tokens in a list of messages
	CountMessageTokens(messages []llm.Message) int
}

// WebSearchService defines the interface for web search operations
type WebSearchService interface {
	// SearchCVE searches for CVE information from the internet
	SearchCVE(ctx context.Context, request *llm.CVESearchRequest) (*llm.CVESearchResponse, error)

	// SearchPackageInfo searches for package/software information
	SearchPackageInfo(ctx context.Context, software string, version string) (map[string]interface{}, error)
}
