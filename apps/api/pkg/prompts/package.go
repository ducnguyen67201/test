package prompts

import "fmt"

// PackageInfoPrompt generates a prompt for gathering package information
func PackageInfoPrompt(software, version string) string {
	return fmt.Sprintf(`Provide information about the following software package in JSON format:

Software: %s
Version: %s

Include:
{
  "package_manager": "apt|npm|pip|gem|cargo|etc",
  "installation_command": "exact command to install this version",
  "common_dependencies": ["list", "of", "common", "dependencies"],
  "official_repository": "URL to official package repository",
  "homepage": "official website URL",
  "license": "software license (e.g., MIT, Apache-2.0, GPL-3.0)",
  "description": "brief one-sentence description",
  "release_date": "approximate release date if known",
  "is_deprecated": true/false,
  "security_notes": "any known security considerations for this version"
}

Only include factual, verifiable information. If you don't know something, omit that field.
Respond with valid JSON only.`, software, version)
}

// PackageVersionResolutionPrompt generates a prompt for resolving version constraints
func PackageVersionResolutionPrompt(software, versionConstraint string) string {
	return fmt.Sprintf(`Given the package "%s" with version constraint "%s", provide the exact version that should be installed.

Examples:
- "node" with ">=16.0.0" → "16.20.2" (latest 16.x)
- "apache2" with "2.4.49" → "2.4.49" (exact)
- "python" with "~3.9" → "3.9.18" (latest 3.9.x)

Respond with ONLY the exact version number (e.g., "2.4.49").
Do not include explanations.`, software, versionConstraint)
}

// PackageDependencyPrompt generates a prompt for identifying dependencies
func PackageDependencyPrompt(software, version string, os string) string {
	return fmt.Sprintf(`List the runtime dependencies required to install and run %s version %s on %s.

Provide response in JSON format:
{
  "system_packages": ["list", "of", "system", "packages"],
  "runtime_dependencies": ["required", "libraries", "or", "frameworks"],
  "optional_dependencies": ["optional", "but", "recommended"],
  "build_dependencies": ["only", "needed", "for", "building"],
  "conflicts": ["packages", "that", "conflict"]
}

Be specific to the OS and version. Only include necessary dependencies.
Respond with valid JSON only.`, software, version, os)
}

// PackageSecurityCheckPrompt generates a prompt for security validation
func PackageSecurityCheckPrompt(packageName, version string) string {
	return fmt.Sprintf(`Analyze the security status of %s version %s.

Provide a JSON response:
{
  "has_known_vulnerabilities": true/false,
  "cve_list": ["CVE-2024-XXXX"],
  "is_outdated": true/false,
  "latest_stable_version": "x.y.z",
  "security_recommendation": "upgrade|acceptable|caution",
  "risk_level": "low|medium|high|critical",
  "notes": "brief explanation of security status"
}

Only include verified CVEs. Be factual and conservative in assessments.
Respond with valid JSON only.`, packageName, version)
}

// PackageInstallationGuidePrompt generates detailed installation instructions
func PackageInstallationGuidePrompt(software, version, os string) string {
	return fmt.Sprintf(`Generate step-by-step installation instructions for %s version %s on %s.

Format as a JSON array of steps:
[
  {
    "step": 1,
    "description": "Update package lists",
    "command": "apt-get update",
    "expected_output": "what the user should see",
    "troubleshooting": "common issues and fixes"
  }
]

Include:
- Repository setup if needed
- Dependency installation
- Main package installation
- Post-installation configuration
- Verification steps

Be specific to the OS. Include actual commands that will work.
Respond with valid JSON only.`, software, version, os)
}
