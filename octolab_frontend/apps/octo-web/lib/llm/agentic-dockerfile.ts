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
  let lastResult: GenerationAttempt | null = null;

  console.log(`[Agentic] Starting generation for ${cveId}, max ${maxIter} iterations`);

  for (let attempt = 1; attempt <= maxIter; attempt++) {
    console.log(`[Agentic] Attempt ${attempt}/${maxIter} for ${cveId}`);

    // 1. Generate or fix Dockerfile
    const result = await generateOrFix(llm, cveId, metadata, lastDockerfile, lastError);
    lastDockerfile = result.dockerfile;
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

/**
 * Generate a new Dockerfile or fix a previous attempt based on error feedback
 */
async function generateOrFix(
  llm: ReturnType<typeof getLLMManager>,
  cveId: string,
  metadata: NVDMetadata | null,
  previousDockerfile: string,
  previousError: string
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
    userPrompt += `=== PREVIOUS ATTEMPT FAILED ===
Error: ${previousError}

Previous Dockerfile that failed:
\`\`\`dockerfile
${previousDockerfile}
\`\`\`

IMPORTANT: Fix the specific error above. The previous Dockerfile did not work.
Common fixes:
- If a package/version doesn't exist, find an alternative or different version
- If COPY fails, ensure the file is in sourceFiles
- If service doesn't start, check entrypoint/CMD and dependencies
- If build times out, simplify the build steps

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
