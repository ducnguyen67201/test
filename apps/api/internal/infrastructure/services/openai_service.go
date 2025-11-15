package services

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/zerozero/apps/api/pkg/llm"
	"github.com/zerozero/apps/api/pkg/logger"
	"github.com/zerozero/apps/api/pkg/prompts"
)

const (
	openAIAPIURL           = "https://api.openai.com/v1/chat/completions"
	defaultModel           = "gpt-4o"
	defaultTemperature     = 0.7
	defaultMaxTokens       = 2000
	estimatedCharsPerToken = 4 // Rough estimate: 1 token ≈ 4 characters
)

// OpenAIService implements LLMService using OpenAI API
type OpenAIService struct {
	apiKey     string
	httpClient *http.Client
	log        logger.Logger
}

// NewOpenAIService creates a new OpenAI service
func NewOpenAIService(apiKey string, log logger.Logger) LLMService {
	return &OpenAIService{
		apiKey: apiKey,
		httpClient: &http.Client{
			Timeout: 60 * time.Second,
		},
		log: log,
	}
}

// Chat sends a chat completion request and returns the response
func (s *OpenAIService) Chat(ctx context.Context, request *llm.CompletionRequest) (*llm.CompletionResponse, error) {
	s.log.Info("Sending chat completion request",
		logger.String("model", request.Model),
		logger.Int("message_count", len(request.Messages)))

	// Set defaults
	if request.Model == "" {
		request.Model = defaultModel
	}
	if request.Temperature == 0 {
		request.Temperature = defaultTemperature
	}
	if request.MaxTokens == 0 {
		request.MaxTokens = defaultMaxTokens
	}
	request.Stream = false

	// Marshal request
	requestBody, err := json.Marshal(request)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Create HTTP request
	httpReq, err := http.NewRequestWithContext(ctx, "POST", openAIAPIURL, bytes.NewReader(requestBody))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", fmt.Sprintf("Bearer %s", s.apiKey))

	// Send request
	resp, err := s.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// Check status code
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("OpenAI API error (status %d): %s", resp.StatusCode, string(body))
	}

	// Parse response
	var response llm.CompletionResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	s.log.Info("Chat completion received",
		logger.String("id", response.ID),
		logger.Int("prompt_tokens", response.Usage.PromptTokens),
		logger.Int("completion_tokens", response.Usage.CompletionTokens),
		logger.Int("total_tokens", response.Usage.TotalTokens))

	return &response, nil
}

// StreamChat sends a chat completion request and streams the response via a channel
func (s *OpenAIService) StreamChat(ctx context.Context, request *llm.CompletionRequest) (<-chan llm.StreamDelta, <-chan error) {
	deltaChan := make(chan llm.StreamDelta, 10)
	errorChan := make(chan error, 1)

	go func() {
		defer close(deltaChan)
		defer close(errorChan)

		s.log.Info("Starting streaming chat completion",
			logger.String("model", request.Model),
			logger.Int("message_count", len(request.Messages)))

		// Set defaults
		if request.Model == "" {
			request.Model = defaultModel
		}
		if request.Temperature == 0 {
			request.Temperature = defaultTemperature
		}
		if request.MaxTokens == 0 {
			request.MaxTokens = defaultMaxTokens
		}
		request.Stream = true

		// Marshal request
		requestBody, err := json.Marshal(request)
		if err != nil {
			errorChan <- fmt.Errorf("failed to marshal request: %w", err)
			return
		}

		// Create HTTP request
		httpReq, err := http.NewRequestWithContext(ctx, "POST", openAIAPIURL, bytes.NewReader(requestBody))
		if err != nil {
			errorChan <- fmt.Errorf("failed to create request: %w", err)
			return
		}

		httpReq.Header.Set("Content-Type", "application/json")
		httpReq.Header.Set("Authorization", fmt.Sprintf("Bearer %s", s.apiKey))

		// Send request
		resp, err := s.httpClient.Do(httpReq)
		if err != nil {
			errorChan <- fmt.Errorf("failed to send request: %w", err)
			return
		}
		defer resp.Body.Close()

		// Check status code
		if resp.StatusCode != http.StatusOK {
			body, _ := io.ReadAll(resp.Body)
			errorChan <- fmt.Errorf("OpenAI API error (status %d): %s", resp.StatusCode, string(body))
			return
		}

		// Read SSE stream
		reader := bufio.NewReader(resp.Body)
		for {
			select {
			case <-ctx.Done():
				errorChan <- ctx.Err()
				return
			default:
			}

			line, err := reader.ReadBytes('\n')
			if err != nil {
				if err == io.EOF {
					return
				}
				errorChan <- fmt.Errorf("error reading stream: %w", err)
				return
			}

			// Skip empty lines
			line = bytes.TrimSpace(line)
			if len(line) == 0 {
				continue
			}

			// SSE format: "data: {...}"
			if !bytes.HasPrefix(line, []byte("data: ")) {
				continue
			}

			// Remove "data: " prefix
			data := bytes.TrimPrefix(line, []byte("data: "))

			// Check for [DONE] signal
			if bytes.Equal(data, []byte("[DONE]")) {
				s.log.Info("Stream completed")
				return
			}

			// Parse delta
			var delta llm.StreamDelta
			if err := json.Unmarshal(data, &delta); err != nil {
				s.log.Warn("Failed to parse delta", logger.Error(err))
				continue
			}

			// Send delta to channel
			select {
			case deltaChan <- delta:
			case <-ctx.Done():
				errorChan <- ctx.Err()
				return
			}
		}
	}()

	return deltaChan, errorChan
}

// ExtractIntent extracts structured intent from conversation history
func (s *OpenAIService) ExtractIntent(ctx context.Context, request *llm.IntentExtractionRequest) (*llm.IntentExtractionResponse, error) {
	s.log.Info("Extracting intent from conversation",
		logger.Int("history_length", len(request.ConversationHistory)))

	// Build messages using prompts package
	messages := []llm.Message{
		{Role: llm.RoleSystem, Content: prompts.IntentExtractionSystemPrompt},
	}
	messages = append(messages, request.ConversationHistory...)
	messages = append(messages, llm.Message{
		Role:    llm.RoleUser,
		Content: prompts.IntentExtractionUserPrompt,
	})

	// Make request with JSON mode
	model := request.Model
	if model == "" {
		model = defaultModel
	}

	temperature := request.Temperature
	if temperature == 0 {
		temperature = 0.3 // Lower temperature for deterministic extraction
	}

	completionReq := &llm.CompletionRequest{
		Model:       model,
		Messages:    messages,
		Temperature: temperature,
		MaxTokens:   2000,
		ResponseFormat: &llm.ResponseFormat{
			Type: "json_object",
		},
	}

	// Get completion
	response, err := s.Chat(ctx, completionReq)
	if err != nil {
		return nil, fmt.Errorf("failed to extract intent: %w", err)
	}

	if len(response.Choices) == 0 {
		return nil, fmt.Errorf("no choices in response")
	}

	// Parse JSON response
	content := response.Choices[0].Message.Content
	var intentData map[string]interface{}
	if err := json.Unmarshal([]byte(content), &intentData); err != nil {
		return nil, fmt.Errorf("failed to parse intent JSON: %w", err)
	}

	// Extract confidence
	confidence := 0.5
	if conf, ok := intentData["confidence"].(float64); ok {
		confidence = conf
	}

	s.log.Info("Intent extracted",
		logger.Any("confidence", confidence),
		logger.Int("tokens_used", response.Usage.TotalTokens))

	return &llm.IntentExtractionResponse{
		Intent:     intentData,
		Confidence: confidence,
		RawJSON:    content,
	}, nil
}

// EstimateTokens estimates the number of tokens in a text
func (s *OpenAIService) EstimateTokens(text string) int {
	// Rough estimate: 1 token ≈ 4 characters
	// For more accuracy, use tiktoken library
	return len(text) / estimatedCharsPerToken
}

// CountMessageTokens counts tokens in a list of messages
func (s *OpenAIService) CountMessageTokens(messages []llm.Message) int {
	total := 0
	for _, msg := range messages {
		// Add tokens for role and content
		total += s.EstimateTokens(string(msg.Role))
		total += s.EstimateTokens(msg.Content)
		// Add overhead per message (OpenAI format overhead)
		total += 4
	}
	// Add overhead for the entire messages array
	total += 3
	return total
}
