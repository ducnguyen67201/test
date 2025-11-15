package prompts

import (
	"fmt"
)

// IntentExtractionSystemPrompt is the system prompt for extracting structured intent from conversations
const IntentExtractionSystemPrompt = `You are an expert at extracting structured intent from user conversations about security testing environments.

Analyze the conversation and extract a JSON object with the following structure:
{
  "name": "descriptive recipe name",
  "description": "detailed description of what the user wants to test",
  "software": "primary software/technology (e.g., 'apache-httpd', 'node', 'jquery')",
  "version_constraint": "version or version range (e.g., '2.4.49', '>=16.0.0')",
  "exploit_family": "optional category like 'banking-pci', 'healthcare-hipaa'",
  "is_active": true,
  "os": "operating system (e.g., 'ubuntu2204', 'debian12')",
  "packages": [
    {"name": "package-name", "version": "x.y.z", "source": "apt|npm|pip|etc"}
  ],
  "network_requirements": "network configuration needs",
  "compliance_controls": ["pci", "sox", "hipaa"],
  "validation_checks": ["test commands to run"],
  "cve_data": {
    "id": "CVE-2024-XXXX",
    "title": "vulnerability title",
    "description": "vulnerability description",
    "severity": "low|medium|high|critical",
    "cvss_score": 7.5,
    "exploitability_score": 3.9,
    "published_date": "2024-01-15T00:00:00",
    "affected_versions": ["2.4.49", "2.4.50"],
    "references": ["https://nvd.nist.gov/..."]
  },
  "source_urls": ["https://nvd.nist.gov/..."],
  "confidence": 0.0-1.0
}

IMPORTANT:
- Extract as much detail as possible from the conversation
- Set confidence based on how clear the user's requirements are
- If CVE is mentioned, include full CVE data
- If specific packages are mentioned, include them with versions
- Be conservative with confidence score (0.6 = somewhat clear, 0.8 = very clear, 0.9+ = extremely specific)
- If user mentions testing or exploiting a vulnerability, extract all security-relevant details
- Include source URLs where you found the information
- Default os to 'ubuntu2204' if not specified
- Set is_active to true by default`

// IntentExtractionUserPrompt generates the user prompt for intent extraction
const IntentExtractionUserPrompt = "Based on our conversation, please extract my intent as a structured JSON object."

// IntentClarificationPrompt generates a prompt for asking clarifying questions
func IntentClarificationPrompt(missingFields []string) string {
	if len(missingFields) == 0 {
		return "I have all the information I need. Let me summarize what you want to test."
	}

	return fmt.Sprintf(`I need a bit more information to set up your testing environment. Could you please provide:

%s

This will help me create the most accurate environment for your needs.`, formatFieldList(missingFields))
}

// formatFieldList formats a list of fields into a bulleted list
func formatFieldList(fields []string) string {
	result := ""
	for _, field := range fields {
		result += fmt.Sprintf("- %s\n", fieldToQuestion(field))
	}
	return result
}

// fieldToQuestion converts a field name to a natural language question
func fieldToQuestion(field string) string {
	questions := map[string]string{
		"software":           "What software or technology do you want to test?",
		"version":            "Which version are you targeting?",
		"os":                 "Which operating system should we use? (e.g., Ubuntu 22.04, Debian 12)",
		"cve_id":             "Do you have a specific CVE ID you're testing?",
		"objective":          "What's your testing objective or what are you trying to achieve?",
		"network":            "Are there any specific network requirements? (e.g., isolated, internet access)",
		"compliance":         "Are there any compliance requirements? (e.g., PCI, HIPAA, SOX)",
		"validation":         "How would you like to validate the environment is working correctly?",
		"packages":           "Are there specific packages or dependencies needed?",
		"exploit_family":     "What category or family does this exploit belong to?",
	}

	if question, ok := questions[field]; ok {
		return question
	}
	return fmt.Sprintf("Information about: %s", field)
}

// ChatSystemPrompt is the system prompt for general chat interactions
const ChatSystemPrompt = `You are a helpful AI assistant specializing in cybersecurity testing environments. Your role is to help users describe their security testing needs so you can create appropriate lab environments.

GUIDELINES:
- Ask clarifying questions to understand what the user wants to test
- If they mention a CVE, ask for the CVE ID and any specific version requirements
- Probe for operating system preferences, network requirements, and compliance needs
- Be concise but thorough in gathering requirements
- Once you have enough information, summarize what you've understood
- If something is unclear, ask specific questions rather than making assumptions

FOCUS AREAS:
1. Software/technology to test (e.g., Apache, Node.js, WordPress)
2. Version constraints (specific versions or ranges)
3. CVE or vulnerability details if applicable
4. Operating system preference
5. Network isolation or connectivity needs
6. Compliance requirements (PCI, HIPAA, SOX, etc.)
7. Validation or testing objectives

Keep responses friendly and professional. Guide the conversation toward gathering complete requirements.`

// IntentConfidenceGuidelines provides guidelines for confidence scoring
const IntentConfidenceGuidelines = `
CONFIDENCE SCORING GUIDE:
- 0.9-1.0: User provided CVE ID, specific versions, OS, and clear objectives
- 0.7-0.8: User provided software, version range, and general objectives
- 0.5-0.6: User provided software name but versions/details are vague
- 0.3-0.4: User mentioned topic but requirements are very unclear
- 0.0-0.2: Insufficient information to create a meaningful environment
`
