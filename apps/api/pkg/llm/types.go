package llm

// Role represents the role of a message sender in a conversation
type Role string

const (
	RoleSystem    Role = "system"
	RoleUser      Role = "user"
	RoleAssistant Role = "assistant"
)

// Message represents a single message in a conversation
type Message struct {
	Role    Role   `json:"role"`
	Content string `json:"content"`
}

// CompletionRequest represents a request for LLM completion
type CompletionRequest struct {
	Model            string              `json:"model"`
	Messages         []Message           `json:"messages"`
	Temperature      float64             `json:"temperature,omitempty"`
	MaxTokens        int                 `json:"max_tokens,omitempty"`
	Stream           bool                `json:"stream,omitempty"`
	Functions        []FunctionDefinition `json:"functions,omitempty"`
	FunctionCall     interface{}         `json:"function_call,omitempty"`
	ResponseFormat   *ResponseFormat     `json:"response_format,omitempty"`
}

// CompletionResponse represents the response from LLM
type CompletionResponse struct {
	ID      string   `json:"id"`
	Object  string   `json:"object"`
	Created int64    `json:"created"`
	Model   string   `json:"model"`
	Choices []Choice `json:"choices"`
	Usage   Usage    `json:"usage"`
}

// Choice represents a completion choice
type Choice struct {
	Index        int         `json:"index"`
	Message      Message     `json:"message"`
	FinishReason string      `json:"finish_reason"`
	Delta        *Message    `json:"delta,omitempty"`
}

// Usage represents token usage information
type Usage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// StreamDelta represents a streaming response chunk
type StreamDelta struct {
	ID      string        `json:"id"`
	Object  string        `json:"object"`
	Created int64         `json:"created"`
	Model   string        `json:"model"`
	Choices []StreamChoice `json:"choices"`
}

// StreamChoice represents a streaming choice
type StreamChoice struct {
	Index        int      `json:"index"`
	Delta        Delta    `json:"delta"`
	FinishReason *string  `json:"finish_reason"`
}

// Delta represents the delta content in streaming
type Delta struct {
	Role    string `json:"role,omitempty"`
	Content string `json:"content,omitempty"`
}

// FunctionDefinition defines a function that the LLM can call
type FunctionDefinition struct {
	Name        string      `json:"name"`
	Description string      `json:"description"`
	Parameters  interface{} `json:"parameters"`
}

// ResponseFormat specifies the response format (e.g., JSON mode)
type ResponseFormat struct {
	Type string `json:"type"` // "text" or "json_object"
}

// IntentExtractionRequest represents a request to extract intent from conversation
type IntentExtractionRequest struct {
	ConversationHistory []Message
	Model               string
	Temperature         float64
}

// IntentExtractionResponse represents the extracted intent
type IntentExtractionResponse struct {
	Intent     interface{} `json:"intent"`
	Confidence float64     `json:"confidence"`
	RawJSON    string      `json:"raw_json"`
}

// CVESearchRequest represents a request to search for CVE information
type CVESearchRequest struct {
	CVEID       string
	Software    string
	Version     string
	Description string
}

// CVESearchResponse represents CVE information from web search
type CVESearchResponse struct {
	CVEID               string   `json:"cve_id"`
	Title               string   `json:"title"`
	Description         string   `json:"description"`
	Severity            string   `json:"severity"`
	CVSSScore           float64  `json:"cvss_score"`
	ExploitabilityScore float64  `json:"exploitability_score"`
	PublishedDate       string   `json:"published_date"`
	AffectedVersions    []string `json:"affected_versions"`
	References          []string `json:"references"`
	SourceURL           string   `json:"source_url"`
}

// String returns the string representation of Role
func (r Role) String() string {
	return string(r)
}
