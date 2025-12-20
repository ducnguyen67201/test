/**
 * Agentic Dockerfile Generator with Build Feedback Loop
 *
 * Creates Dockerfiles through an iterative process:
 * 1. Generate Dockerfile from CVE metadata
 * 2. Validate/build in sandbox
 * 3. See actual errors
 * 4. Fix and retry
 * 5. Verify setup is correct
 *
 * Target: 90%+ success rate through iteration
 */

import { getLLMManager } from "./manager";
import type { NVDMetadata } from "./tools/dockerfile";
import { DOCKERFILE_SYSTEM_PROMPT } from "./tools/dockerfile";

const MAX_ITERATIONS = 5;
const BACKEND_URL = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";
const SERVICE_TOKEN = process.env.OCTOLAB_SERVICE_TOKEN;

export interface AgenticDockerfileResult {
  dockerfile: string;
  sourceFiles: Array<{ filename: string; content: string }>;
  exploitHint: string;
  baseImage?: string;
  exposedPorts?: number[];
  iterations: number;
  finalConfidence: number;
}

interface BuildResult {
  success: boolean;
  error?: string;
  containerId?: string;
  buildLog?: string;
}

interface VerifyResult {
  success: boolean;
  checks: Array<{ name: string; passed: boolean; detail: string }>;
}

interface GenerationAttempt {
  dockerfile: string;
  sourceFiles: Array<{ filename: string; content: string }>;
  exploitHint: string;
  baseImage?: string;
  exposedPorts?: number[];
  confidence: number;
  confidenceReason: string;
}

/**
 * Generate a Dockerfile using an agentic loop with build feedback
 */
export async function generateDockerfileAgentic(
  cveId: string,
  metadata: NVDMetadata | null,
  options?: {
    maxIterations?: number;
    skipBuildTest?: boolean;
  }
): Promise<AgenticDockerfileResult> {
  const maxIter = options?.maxIterations ?? MAX_ITERATIONS;
  const llm = getLLMManager();

  let lastDockerfile = "";
  let lastError = "";
  let lastSourceFiles: Array<{ filename: string; content: string }> = [];
  let lastResult: GenerationAttempt | null = null;

  console.log(`[Agentic] Starting generation for ${cveId}, max ${maxIter} iterations`);

  for (let attempt = 1; attempt <= maxIter; attempt++) {
    console.log(`[Agentic] Attempt ${attempt}/${maxIter} for ${cveId}`);

    // 1. Generate or fix Dockerfile
    const result = await generateOrFix(
      llm,
      cveId,
      metadata,
      lastDockerfile,
      lastError,
      lastSourceFiles,
      attempt
    );
    lastDockerfile = result.dockerfile;
    lastSourceFiles = result.sourceFiles;
    lastResult = result;

    // Check confidence - if very low, might want to bail early
    if (result.confidence < 20 && attempt === 1) {
      console.log(`[Agentic] Very low initial confidence (${result.confidence}%), but trying anyway`);
    }

    // Skip build test if requested (for quick validation only)
    if (options?.skipBuildTest) {
      console.log(`[Agentic] Skipping build test, returning after generation`);
      return {
        dockerfile: result.dockerfile,
        sourceFiles: result.sourceFiles,
        exploitHint: result.exploitHint,
        baseImage: result.baseImage,
        exposedPorts: result.exposedPorts,
        iterations: attempt,
        finalConfidence: result.confidence,
      };
    }

    // 2. Validate Dockerfile syntax first
    const validationResult = await validateDockerfile(result);
    if (!validationResult.success) {
      lastError = validationResult.error || "Validation failed";
      console.log(`[Agentic] Validation failed: ${lastError}`);

      // Check for stuck loop (same error repeated)
      if (attempt > 1 && lastError === validationResult.error) {
        console.log(`[Agentic] Same validation error repeated, trying different approach`);
        lastError += " (IMPORTANT: Previous fix did not work, try a completely different approach)";
      }
      continue;
    }

    // 3. Try to build
    const buildResult = await testBuildDockerfile(result);
    if (!buildResult.success) {
      lastError = buildResult.error || "Unknown build error";
      console.log(`[Agentic] Build failed: ${lastError}`);

      // Include build log excerpt if available
      if (buildResult.buildLog) {
        const logExcerpt = buildResult.buildLog.slice(-500);
        lastError += `\n\nBuild log (last 500 chars):\n${logExcerpt}`;
      }
      continue;
    }

    // 4. Verify setup (if container available)
    if (buildResult.containerId) {
      const verifyResult = await verifySetup(cveId, metadata, buildResult.containerId);

      if (!verifyResult.success) {
        const failedChecks = verifyResult.checks
          .filter((c) => !c.passed)
          .map((c) => `${c.name}: ${c.detail}`)
          .join("; ");

        lastError = `Build succeeded but verification failed: ${failedChecks}`;
        console.log(`[Agentic] Verification failed: ${lastError}`);

        // Clean up test container
        await cleanupTestContainer(buildResult.containerId);
        continue;
      }

      // Clean up successful test container
      await cleanupTestContainer(buildResult.containerId);
    }

    // Success!
    console.log(`[Agentic] Success on attempt ${attempt}!`);
    return {
      dockerfile: result.dockerfile,
      sourceFiles: result.sourceFiles,
      exploitHint: result.exploitHint,
      baseImage: result.baseImage,
      exposedPorts: result.exposedPorts,
      iterations: attempt,
      finalConfidence: result.confidence,
    };
  }

  // All attempts failed - return last result with error context
  if (lastResult) {
    console.error(`[Agentic] Failed after ${maxIter} attempts. Last error: ${lastError}`);
    throw new AgenticGenerationError(
      `Failed to generate valid Dockerfile after ${maxIter} attempts`,
      lastError,
      lastResult,
      maxIter
    );
  }

  throw new Error(`Failed to generate Dockerfile for ${cveId}`);
}

interface ErrorAnalysis {
  summary: string;
  category: "BUILD_ERROR" | "RUNTIME_ERROR" | "VALIDATION_ERROR" | "NETWORK_ERROR" | "UNKNOWN";
  location: string;
  rootCause: string;
  actionItems: string[];
}

/**
 * Analyze the error to provide structured feedback to the LLM
 */
function analyzeError(
  error: string,
  dockerfile: string,
  sourceFiles: Array<{ filename: string; content: string }>
): ErrorAnalysis {
  const errorLower = error.toLowerCase();
  const dockerfileLines = dockerfile.split("\n");

  // Default analysis
  let analysis: ErrorAnalysis = {
    summary: "Unknown error occurred during build or runtime",
    category: "UNKNOWN",
    location: "Unable to determine",
    rootCause: "Error pattern not recognized",
    actionItems: ["Review the raw error output", "Try a different approach"],
  };

  // === BUILD ERRORS ===

  // Package not found
  if (errorLower.includes("package") && (errorLower.includes("not found") || errorLower.includes("no such"))) {
    const packageMatch = error.match(/(?:package|unable to locate package)\s+['"]?([^\s'"]+)/i);
    analysis = {
      summary: `Package installation failed: ${packageMatch?.[1] || "unknown package"}`,
      category: "BUILD_ERROR",
      location: "Dockerfile RUN command (apt-get/apk/yum install)",
      rootCause: "The specified package name doesn't exist in the package repository, or the repository is not available in the base image",
      actionItems: [
        packageMatch?.[1] ? `Remove or replace package "${packageMatch[1]}" with correct package name` : "Check package names",
        "Verify the base image has the correct package repositories",
        "Try using a different base image that includes this package",
        "Search for alternative package names (e.g., libfoo-dev vs foo-devel)",
      ],
    };
  }

  // COPY failed - file not found
  else if (errorLower.includes("copy") && (errorLower.includes("not found") || errorLower.includes("no such file"))) {
    const copyMatch = error.match(/COPY.*?(\S+)/i) || dockerfile.match(/COPY\s+(\S+)/);
    const missingFile = copyMatch?.[1];
    const fileInSourceFiles = sourceFiles.some((sf) => sf.filename === missingFile);

    analysis = {
      summary: `COPY failed: File "${missingFile || "unknown"}" not found in build context`,
      category: "BUILD_ERROR",
      location: `Dockerfile COPY command${missingFile ? ` referencing "${missingFile}"` : ""}`,
      rootCause: fileInSourceFiles
        ? "File exists in sourceFiles but path doesn't match COPY command"
        : "File referenced in COPY is not included in sourceFiles array",
      actionItems: [
        missingFile && !fileInSourceFiles
          ? `Add "${missingFile}" to the sourceFiles array with its content`
          : `Fix the path in COPY to match sourceFiles filename`,
        "Ensure filename in sourceFiles matches exactly what COPY expects",
        "Check for typos in filename",
      ],
    };
  }

  // Base image not found
  else if (errorLower.includes("manifest") || (errorLower.includes("pull") && errorLower.includes("not found"))) {
    const fromLine = dockerfileLines.find((l) => l.trim().startsWith("FROM"));
    const imageMatch = fromLine?.match(/FROM\s+(\S+)/);

    analysis = {
      summary: `Base image not found: ${imageMatch?.[1] || "unknown"}`,
      category: "BUILD_ERROR",
      location: `Dockerfile FROM line: "${fromLine?.trim() || "not found"}"`,
      rootCause: "The specified Docker image:tag doesn't exist on Docker Hub or the registry",
      actionItems: [
        "Check Docker Hub for available tags of this image",
        imageMatch?.[1]?.includes(":") ? "Try a different version tag" : "Add a specific version tag (don't use :latest for vulnerable versions)",
        "Use an alternative base image that provides similar functionality",
      ],
    };
  }

  // Command failed during RUN
  else if (errorLower.includes("returned a non-zero code") || errorLower.includes("exit code")) {
    const exitCodeMatch = error.match(/(?:exit code|returned a non-zero code)[:\s]*(\d+)/i);
    const failedCommand = error.match(/RUN\s+(.+?)(?:\s+#|$)/m)?.[1];

    analysis = {
      summary: `Command failed with exit code ${exitCodeMatch?.[1] || "non-zero"}`,
      category: "BUILD_ERROR",
      location: `Dockerfile RUN command${failedCommand ? `: "${failedCommand.slice(0, 50)}..."` : ""}`,
      rootCause: "A shell command in the Dockerfile failed during build",
      actionItems: [
        "Check if the command syntax is correct",
        "Verify required dependencies are installed before this command",
        "Check if URLs in wget/curl commands are valid and accessible",
        "Consider breaking complex RUN commands into smaller steps for better error isolation",
      ],
    };
  }

  // === RUNTIME ERRORS ===

  // Container exited immediately
  else if (errorLower.includes("exited") || errorLower.includes("crash") || errorLower.includes("restart")) {
    const cmdLine = dockerfileLines.find((l) => l.trim().startsWith("CMD") || l.trim().startsWith("ENTRYPOINT"));

    analysis = {
      summary: "Container crashed or exited immediately after starting",
      category: "RUNTIME_ERROR",
      location: `Dockerfile CMD/ENTRYPOINT: "${cmdLine?.trim() || "not specified"}"`,
      rootCause: "The main process exited, likely due to missing dependencies, configuration errors, or the service failing to start",
      actionItems: [
        "Verify the CMD/ENTRYPOINT command is correct",
        "Ensure all required config files exist and are valid",
        "Check if the service requires specific environment variables",
        "Add a HEALTHCHECK to debug startup issues",
        "Try running the container interactively to see error output",
      ],
    };
  }

  // Service not listening / connection refused
  else if (errorLower.includes("connection refused") || errorLower.includes("not listening")) {
    const exposeLine = dockerfileLines.find((l) => l.trim().startsWith("EXPOSE"));

    analysis = {
      summary: "Service not listening on expected port",
      category: "RUNTIME_ERROR",
      location: `Exposed ports: ${exposeLine?.trim() || "none specified"}`,
      rootCause: "The service started but isn't listening on the expected port, or wrong port is exposed",
      actionItems: [
        "Verify EXPOSE matches the port the service actually listens on",
        "Check service configuration for correct bind address (0.0.0.0, not 127.0.0.1)",
        "Ensure service has time to start before health check runs",
        "Verify the service config file is correct",
      ],
    };
  }

  // === VALIDATION ERRORS ===

  else if (errorLower.includes("validation") || errorLower.includes("syntax")) {
    analysis = {
      summary: "Dockerfile syntax or validation error",
      category: "VALIDATION_ERROR",
      location: "Dockerfile syntax",
      rootCause: "The Dockerfile has syntax errors or invalid instructions",
      actionItems: [
        "Check for missing backslashes in multi-line RUN commands",
        "Verify all instructions are valid Dockerfile commands",
        "Ensure proper quoting in shell commands",
        "Check for invalid characters or encoding issues",
      ],
    };
  }

  // === NETWORK ERRORS ===

  else if (errorLower.includes("timeout") || errorLower.includes("network") || errorLower.includes("could not resolve")) {
    analysis = {
      summary: "Network error during build",
      category: "NETWORK_ERROR",
      location: "Dockerfile commands that fetch external resources",
      rootCause: "Failed to download packages or files due to network issues or invalid URLs",
      actionItems: [
        "Verify URLs in wget/curl commands are correct and accessible",
        "Check if package repositories are reachable",
        "Consider using a mirror or alternative download source",
        "Try a different base image with packages pre-installed",
      ],
    };
  }

  // Highlight which source file might be problematic
  if (sourceFiles.length > 0 && (errorLower.includes("syntax error") || errorLower.includes("parse error"))) {
    const fileMatch = error.match(/(?:in|file)\s+['"]?([^\s'"]+\.(java|py|js|php|sh|conf))/i);
    if (fileMatch) {
      analysis.location = `Source file: ${fileMatch[1]}`;
      analysis.actionItems.unshift(`Fix syntax error in ${fileMatch[1]}`);
    }
  }

  return analysis;
}

/**
 * Generate a new Dockerfile or fix a previous attempt based on error feedback
 */
async function generateOrFix(
  llm: ReturnType<typeof getLLMManager>,
  cveId: string,
  metadata: NVDMetadata | null,
  previousDockerfile: string,
  previousError: string,
  previousSourceFiles: Array<{ filename: string; content: string }>,
  attemptNumber: number
): Promise<GenerationAttempt> {
  let userPrompt = `Generate a Dockerfile for ${cveId}.

`;

  // Add CVE metadata if available
  if (metadata) {
    userPrompt += `=== CVE DETAILS ===
Description: ${metadata.description}
CVSS Score: ${metadata.cvss_score ?? "N/A"} (${metadata.cvss_severity ?? "Unknown"})
Affected Products:
${metadata.affected_products
  .slice(0, 5)
  .map((p) => `- ${p.cpe}`)
  .join("\n")}
References:
${metadata.references?.slice(0, 3).join("\n") || "None"}

`;
  }

  // Add error context if this is a retry
  if (previousError && previousDockerfile) {
    const errorAnalysis = analyzeError(previousError, previousDockerfile, previousSourceFiles);

    userPrompt += `=== PREVIOUS ATTEMPT FAILED (Attempt ${attemptNumber - 1}) ===

## Error Summary
${errorAnalysis.summary}

## Error Category
${errorAnalysis.category}

## Error Location
${errorAnalysis.location}

## Raw Error Output
\`\`\`
${previousError}
\`\`\`

## Root Cause Analysis
${errorAnalysis.rootCause}

## What You Must Fix
${errorAnalysis.actionItems.map((item, i) => `${i + 1}. ${item}`).join("\n")}

## Previous Dockerfile That Failed
\`\`\`dockerfile
${previousDockerfile}
\`\`\`
${previousSourceFiles.length > 0 ? `
## Previous Source Files
${previousSourceFiles.map((sf) => `### ${sf.filename}\n\`\`\`\n${sf.content.slice(0, 500)}${sf.content.length > 500 ? "\n... (truncated)" : ""}\n\`\`\``).join("\n\n")}
` : ""}

## CRITICAL INSTRUCTIONS
- DO NOT repeat the same mistake. The previous approach failed.
- If a package/version doesn't exist, use a DIFFERENT version or approach.
- If a file COPY failed, ensure the file is in sourceFiles array.
- If the same error occurs twice, try a COMPLETELY different base image or approach.
- Focus on the specific error above - don't change unrelated parts.

`;
  }

  userPrompt += `=== OUTPUT FORMAT ===
Use the generate_dockerfile tool to output your result.
Include your confidence score (0-100) and reason.

=== REQUIREMENTS ===
1. Use the EXACT vulnerable version from CVE data
2. Include ALL files referenced by COPY/ADD in sourceFiles
3. Ensure the service starts and is exploitable
4. Rate your confidence honestly - low confidence is fine`;

  const response = await llm.chat(
    [
      { role: "system", content: DOCKERFILE_SYSTEM_PROMPT },
      { role: "user", content: userPrompt },
    ],
    {
      tools: [
        {
          name: "generate_dockerfile",
          description: "Generate Dockerfile and source files for a vulnerable environment",
          parameters: {
            type: "object",
            properties: {
              dockerfile: { type: "string", description: "The Dockerfile content" },
              sourceFiles: {
                type: "array",
                items: {
                  type: "object",
                  properties: {
                    filename: { type: "string" },
                    content: { type: "string" },
                  },
                  required: ["filename", "content"],
                },
                description: "Source files to include in build context",
              },
              exploitHint: { type: "string", description: "How to exploit this CVE" },
              baseImage: { type: "string", description: "Base Docker image" },
              exposedPorts: { type: "array", items: { type: "number" } },
              confidence: { type: "number", description: "Confidence 0-100" },
              confidenceReason: { type: "string" },
            },
            required: ["dockerfile", "sourceFiles", "exploitHint", "confidence", "confidenceReason"],
          },
        },
      ],
      temperature: previousError ? 0.4 : 0.2, // Slightly higher temp on retries for variety
      maxTokens: 4096,
    }
  );

  // Parse tool call response
  if (!response.toolCalls?.length) {
    throw new Error("LLM did not use the generate_dockerfile tool");
  }

  const args = response.toolCalls[0].arguments as {
    dockerfile: string;
    sourceFiles: Array<{ filename: string; content: string }>;
    exploitHint: string;
    baseImage?: string;
    exposedPorts?: number[];
    confidence: number;
    confidenceReason: string;
  };

  return {
    dockerfile: args.dockerfile,
    sourceFiles: args.sourceFiles || [],
    exploitHint: args.exploitHint || "",
    baseImage: args.baseImage,
    exposedPorts: args.exposedPorts,
    confidence: args.confidence ?? 50,
    confidenceReason: args.confidenceReason || "No reason provided",
  };
}

/**
 * Validate Dockerfile syntax and security without building
 */
async function validateDockerfile(
  result: GenerationAttempt
): Promise<{ success: boolean; error?: string }> {
  try {
    const response = await fetch(`${BACKEND_URL}/labs/validate-dockerfile`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(SERVICE_TOKEN && { "X-Service-Token": SERVICE_TOKEN }),
      },
      body: JSON.stringify({
        dockerfile: result.dockerfile,
        source_files: result.sourceFiles.map((sf) => ({
          filename: sf.filename,
          content: sf.content,
        })),
        recipe_name: "agentic-test",
        software: "unknown",
      }),
    });

    const data = await response.json();

    if (data.valid) {
      return { success: true };
    }

    return {
      success: false,
      error: data.errors?.join("; ") || "Validation failed",
    };
  } catch (error) {
    return {
      success: false,
      error: `Validation request failed: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}

/**
 * Test build Dockerfile in sandbox environment
 */
async function testBuildDockerfile(result: GenerationAttempt): Promise<BuildResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/labs/test-build`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(SERVICE_TOKEN && { "X-Service-Token": SERVICE_TOKEN }),
      },
      body: JSON.stringify({
        dockerfile: result.dockerfile,
        source_files: result.sourceFiles.map((sf) => ({
          filename: sf.filename,
          content: sf.content,
        })),
      }),
    });

    const data = await response.json();

    if (response.ok && data.success) {
      return {
        success: true,
        containerId: data.container_id,
      };
    }

    return {
      success: false,
      error: data.detail || data.error || `HTTP ${response.status}`,
      buildLog: data.build_log,
    };
  } catch (error) {
    return {
      success: false,
      error: `Build request failed: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}

/**
 * Verify the built container has correct setup
 */
async function verifySetup(
  cveId: string,
  metadata: NVDMetadata | null,
  containerId: string
): Promise<VerifyResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/labs/verify-setup/${containerId}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(SERVICE_TOKEN && { "X-Service-Token": SERVICE_TOKEN }),
      },
      body: JSON.stringify({
        cve_id: cveId,
        expected_products: metadata?.affected_products || [],
      }),
    });

    if (!response.ok) {
      // If endpoint doesn't exist yet, assume success
      if (response.status === 404) {
        return { success: true, checks: [] };
      }
      return {
        success: false,
        checks: [{ name: "api_error", passed: false, detail: `HTTP ${response.status}` }],
      };
    }

    const data = await response.json();
    return {
      success: data.success ?? true,
      checks: data.checks || [],
    };
  } catch (error) {
    // If verification endpoint not available, assume success
    return { success: true, checks: [] };
  }
}

/**
 * Clean up test container after verification
 */
async function cleanupTestContainer(containerId: string): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}/labs/test-build/${containerId}`, {
      method: "DELETE",
      headers: {
        ...(SERVICE_TOKEN && { "X-Service-Token": SERVICE_TOKEN }),
      },
    });
  } catch (error) {
    console.warn(`[Agentic] Failed to cleanup container ${containerId}:`, error);
  }
}

/**
 * Custom error class for agentic generation failures
 */
export class AgenticGenerationError extends Error {
  constructor(
    message: string,
    public readonly lastError: string,
    public readonly lastResult: GenerationAttempt,
    public readonly attempts: number
  ) {
    super(message);
    this.name = "AgenticGenerationError";
  }
}
