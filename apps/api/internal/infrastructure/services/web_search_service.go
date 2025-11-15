package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/zerozero/apps/api/pkg/llm"
	"github.com/zerozero/apps/api/pkg/logger"
	"github.com/zerozero/apps/api/pkg/prompts"
)

const (
	nvdAPIURL     = "https://services.nvd.nist.gov/rest/json/cves/2.0"
	nvdTimeout    = 30 * time.Second
)

// NVDWebSearchService implements WebSearchService using NVD API
type NVDWebSearchService struct {
	httpClient *http.Client
	log        logger.Logger
	llmService LLMService // Use LLM for enhanced search when needed
}

// NewNVDWebSearchService creates a new NVD web search service
func NewNVDWebSearchService(log logger.Logger, llmService LLMService) WebSearchService {
	return &NVDWebSearchService{
		httpClient: &http.Client{
			Timeout: nvdTimeout,
		},
		log:        log,
		llmService: llmService,
	}
}

// NVDResponse represents the structure of NVD API response
type NVDResponse struct {
	ResultsPerPage int        `json:"resultsPerPage"`
	StartIndex     int        `json:"startIndex"`
	TotalResults   int        `json:"totalResults"`
	Vulnerabilities []struct {
		CVE struct {
			ID          string `json:"id"`
			SourceIdentifier string `json:"sourceIdentifier"`
			Published   string `json:"published"`
			LastModified string `json:"lastModified"`
			VulnStatus  string `json:"vulnStatus"`
			Descriptions []struct {
				Lang  string `json:"lang"`
				Value string `json:"value"`
			} `json:"descriptions"`
			Metrics struct {
				CVSSMetricV31 []struct {
					CvssData struct {
						Version      string  `json:"version"`
						VectorString string  `json:"vectorString"`
						BaseScore    float64 `json:"baseScore"`
						BaseSeverity string  `json:"baseSeverity"`
					} `json:"cvssData"`
					ExploitabilityScore float64 `json:"exploitabilityScore"`
					ImpactScore         float64 `json:"impactScore"`
				} `json:"cvssMetricV31"`
				CVSSMetricV2 []struct {
					CvssData struct {
						Version      string  `json:"version"`
						VectorString string  `json:"vectorString"`
						BaseScore    float64 `json:"baseScore"`
					} `json:"cvssData"`
					ExploitabilityScore float64 `json:"exploitabilityScore"`
					ImpactScore         float64 `json:"impactScore"`
				} `json:"cvssMetricV2"`
			} `json:"metrics"`
			References []struct {
				URL    string   `json:"url"`
				Source string   `json:"source"`
				Tags   []string `json:"tags"`
			} `json:"references"`
		} `json:"cve"`
	} `json:"vulnerabilities"`
}

// SearchCVE searches for CVE information from NVD
func (s *NVDWebSearchService) SearchCVE(ctx context.Context, request *llm.CVESearchRequest) (*llm.CVESearchResponse, error) {
	s.log.Info("Searching for CVE information",
		logger.String("cve_id", request.CVEID),
		logger.String("software", request.Software))

	// If CVE ID is provided, search by ID
	if request.CVEID != "" {
		return s.searchByCVEID(ctx, request.CVEID)
	}

	// If no CVE ID, use LLM to help find relevant CVEs
	if request.Software != "" || request.Description != "" {
		return s.searchByKeywords(ctx, request)
	}

	return nil, fmt.Errorf("either CVE ID or software/description must be provided")
}

// searchByCVEID searches for a specific CVE by ID
func (s *NVDWebSearchService) searchByCVEID(ctx context.Context, cveID string) (*llm.CVESearchResponse, error) {
	// Build URL
	params := url.Values{}
	params.Add("cveId", cveID)

	requestURL := fmt.Sprintf("%s?%s", nvdAPIURL, params.Encode())

	s.log.Info("Fetching CVE from NVD", logger.String("cve_id", cveID))

	// Create request
	req, err := http.NewRequestWithContext(ctx, "GET", requestURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	// Send request
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch CVE data: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("NVD API error (status %d): %s", resp.StatusCode, string(body))
	}

	// Parse response
	var nvdResp NVDResponse
	if err := json.NewDecoder(resp.Body).Decode(&nvdResp); err != nil {
		return nil, fmt.Errorf("failed to decode NVD response: %w", err)
	}

	if len(nvdResp.Vulnerabilities) == 0 {
		return nil, fmt.Errorf("CVE not found: %s", cveID)
	}

	// Extract first result
	cve := nvdResp.Vulnerabilities[0].CVE

	// Get description (prefer English)
	description := ""
	for _, desc := range cve.Descriptions {
		if desc.Lang == "en" {
			description = desc.Value
			break
		}
	}
	if description == "" && len(cve.Descriptions) > 0 {
		description = cve.Descriptions[0].Value
	}

	// Get CVSS metrics
	var cvssScore float64
	var severity string
	var exploitabilityScore float64
	var references []string

	// Try CVSS v3.1 first
	if len(cve.Metrics.CVSSMetricV31) > 0 {
		metric := cve.Metrics.CVSSMetricV31[0]
		cvssScore = metric.CvssData.BaseScore
		severity = strings.ToLower(metric.CvssData.BaseSeverity)
		exploitabilityScore = metric.ExploitabilityScore
	} else if len(cve.Metrics.CVSSMetricV2) > 0 {
		// Fall back to CVSS v2
		metric := cve.Metrics.CVSSMetricV2[0]
		cvssScore = metric.CvssData.BaseScore
		exploitabilityScore = metric.ExploitabilityScore
		// Map score to severity
		if cvssScore >= 9.0 {
			severity = "critical"
		} else if cvssScore >= 7.0 {
			severity = "high"
		} else if cvssScore >= 4.0 {
			severity = "medium"
		} else {
			severity = "low"
		}
	}

	// Extract references
	for _, ref := range cve.References {
		references = append(references, ref.URL)
	}

	response := &llm.CVESearchResponse{
		CVEID:               cve.ID,
		Title:               fmt.Sprintf("Vulnerability in %s", cveID),
		Description:         description,
		Severity:            severity,
		CVSSScore:           cvssScore,
		ExploitabilityScore: exploitabilityScore,
		PublishedDate:       cve.Published,
		References:          references,
		SourceURL:           fmt.Sprintf("https://nvd.nist.gov/vuln/detail/%s", cveID),
	}

	s.log.Info("CVE data retrieved",
		logger.String("cve_id", cveID),
		logger.Any("cvss_score", cvssScore),
		logger.String("severity", severity))

	return response, nil
}

// searchByKeywords uses LLM to help find relevant CVEs
func (s *NVDWebSearchService) searchByKeywords(ctx context.Context, request *llm.CVESearchRequest) (*llm.CVESearchResponse, error) {
	// Use LLM to extract likely CVE ID using prompts package
	prompt := prompts.CVEIdentificationPrompt(request.Software, request.Version, request.Description)

	llmRequest := &llm.CompletionRequest{
		Model: defaultModel,
		Messages: []llm.Message{
			{Role: llm.RoleSystem, Content: prompts.CVESearchAssistPrompt},
			{Role: llm.RoleUser, Content: prompt},
		},
		Temperature: 0.3,
		MaxTokens:   100,
	}

	response, err := s.llmService.Chat(ctx, llmRequest)
	if err != nil {
		return nil, fmt.Errorf("failed to query LLM for CVE: %w", err)
	}

	if len(response.Choices) == 0 {
		return nil, fmt.Errorf("no response from LLM")
	}

	cveID := strings.TrimSpace(response.Choices[0].Message.Content)

	// Check if we got a CVE ID
	if strings.HasPrefix(strings.ToUpper(cveID), "CVE-") {
		// Search by the identified CVE ID
		return s.searchByCVEID(ctx, strings.ToUpper(cveID))
	}

	// If no CVE found, return a mock response
	s.log.Warn("No specific CVE identified",
		logger.String("software", request.Software),
		logger.String("version", request.Version))

	return &llm.CVESearchResponse{
		CVEID:       "CVE-UNKNOWN",
		Title:       fmt.Sprintf("Vulnerability in %s %s", request.Software, request.Version),
		Description: request.Description,
		Severity:    "medium",
		CVSSScore:   5.0,
		References:  []string{},
		SourceURL:   "",
	}, nil
}

// SearchPackageInfo searches for package/software information
func (s *NVDWebSearchService) SearchPackageInfo(ctx context.Context, software string, version string) (map[string]interface{}, error) {
	s.log.Info("Searching for package information",
		logger.String("software", software),
		logger.String("version", version))

	// Use LLM to gather package information using prompts package
	prompt := prompts.PackageInfoPrompt(software, version)

	llmRequest := &llm.CompletionRequest{
		Model: defaultModel,
		Messages: []llm.Message{
			{Role: llm.RoleUser, Content: prompt},
		},
		Temperature: 0.3,
		MaxTokens:   500,
		ResponseFormat: &llm.ResponseFormat{
			Type: "json_object",
		},
	}

	response, err := s.llmService.Chat(ctx, llmRequest)
	if err != nil {
		return nil, fmt.Errorf("failed to query LLM for package info: %w", err)
	}

	if len(response.Choices) == 0 {
		return nil, fmt.Errorf("no response from LLM")
	}

	var packageInfo map[string]interface{}
	if err := json.Unmarshal([]byte(response.Choices[0].Message.Content), &packageInfo); err != nil {
		return nil, fmt.Errorf("failed to parse package info: %w", err)
	}

	s.log.Info("Package information retrieved", logger.String("software", software))

	return packageInfo, nil
}
