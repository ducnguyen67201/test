package prompts

import "fmt"

// CVEIdentificationPrompt generates a prompt for identifying CVE from description
func CVEIdentificationPrompt(software, version, description string) string {
	return fmt.Sprintf(`Based on the following information, identify the most likely CVE ID:

Software: %s
Version: %s
Description: %s

If you can identify a specific CVE ID, respond with ONLY the CVE ID (e.g., CVE-2024-1234).
If you cannot identify a specific CVE, respond with "UNKNOWN".

Do not include any explanation or additional text.`, software, version, description)
}

// CVESearchAssistPrompt generates a prompt for helping with CVE search
const CVESearchAssistPrompt = `You are a cybersecurity expert helping identify CVE (Common Vulnerabilities and Exposures) identifiers.

When given software and version information:
1. If you recognize a specific CVE, provide ONLY the CVE ID
2. If you don't know a specific CVE, respond with "UNKNOWN"
3. Never make up or guess CVE IDs
4. Only provide CVE IDs you're confident about

Examples:
- Input: "Apache Struts 2.5.10, remote code execution" → "CVE-2017-5638"
- Input: "Some random software, unknown issue" → "UNKNOWN"`

// CVEEnrichmentPrompt generates a prompt for enriching CVE data with LLM knowledge
func CVEEnrichmentPrompt(cveID string) string {
	return fmt.Sprintf(`Provide detailed information about %s in JSON format:

{
  "summary": "Brief one-sentence summary",
  "attack_vector": "How the vulnerability can be exploited",
  "affected_components": ["list", "of", "components"],
  "mitigation": "How to fix or mitigate",
  "public_exploits_available": true/false,
  "exploitation_difficulty": "trivial|easy|medium|hard",
  "real_world_impact": "Brief description of known incidents"
}

Only include verified, factual information. If you don't know something, omit that field.`, cveID)
}

// CVESeverityExplanationPrompt generates a prompt for explaining severity
func CVESeverityExplanationPrompt(cvssScore float64, severity string) string {
	return fmt.Sprintf(`Explain in 1-2 sentences why this vulnerability has a CVSS score of %.1f (%s severity) in simple terms for a security engineer.

Focus on:
- Attack complexity
- Required privileges
- User interaction needed
- Scope of impact

Keep it concise and technical.`, cvssScore, severity)
}
