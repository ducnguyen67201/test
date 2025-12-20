import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { createTRPCRouter, protectedProcedure, adminProcedure } from "../init";
import { recipeCreateSchema } from "@/lib/schemas/recipe";
import {
  getLLMManager,
  ConversationManager,
  recipeTools,
  RECIPE_SYSTEM_PROMPT,
  formatToolCallResult,
  dockerfileTools,
  DOCKERFILE_SYSTEM_PROMPT,
  buildDockerfilePrompt,
  type NVDMetadata,
} from "@/lib/llm";

/**
 * Response schema for chat endpoint
 */
const chatResponseSchema = z.object({
  message: z.string(),
  recipe: z
    .object({
      name: z.string(),
      description: z.string(),
      software: z.string(),
      version_constraint: z.string().nullable().optional(),
      exploit_family: z.string().nullable().optional(),
      is_active: z.boolean().optional(),
    })
    .nullable()
    .optional(),
  confidence: z.number().optional(),
  suggestions: z.array(z.string()).optional(),
  conversationId: z.string(),
});

export const recipeRouter = createTRPCRouter({
  /**
   * Process a chat message using LLM with tool calling
   */
  chat: protectedProcedure
    .input(
      z.object({
        message: z.string().min(1).max(10000),
        conversationId: z.string().optional(),
      })
    )
    .output(chatResponseSchema)
    .mutation(async ({ ctx, input }) => {
      const llm = getLLMManager();

      // Get or create conversation
      const conversation = ConversationManager.getOrCreate(
        input.conversationId ?? null,
        ctx.session.user.id
      );

      // Try to resolve CVE reference (ID or alias like "log4shell", "react2shell")
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";
      let nvdContext = "";
      let cachedCveInfo: { cve_id: string; exploit_hint?: string } | null = null;

      // Extract potential reference from message (first word or CVE pattern)
      const cvePattern = /CVE-\d{4}-\d{4,}/i;
      const cveMatch = input.message.match(cvePattern);
      // Also try common vulnerability names (single word references)
      const words = input.message.toLowerCase().split(/\s+/);
      const potentialAlias = words.find((w) =>
        /^[a-z0-9-]+shell$|^log4j|^spring4shell|^heartbleed|^shellshock|^dirty\s*cow|^eternal\s*blue/i.test(w)
      );
      const reference = cveMatch?.[0] || potentialAlias || "";

      if (reference) {
        try {
          // First, try the resolve endpoint (handles both CVE IDs and aliases)
          const resolveResponse = await fetch(`${octoLabBaseUrl}/cve-registry/resolve/${encodeURIComponent(reference)}`);

          if (resolveResponse.ok) {
            const resolved = await resolveResponse.json();
            if (resolved.found) {
              console.log(`[Chat] Resolved '${reference}' to cached CVE ${resolved.cve_id}`);
              cachedCveInfo = {
                cve_id: resolved.cve_id,
                exploit_hint: resolved.exploit_hint,
              };

              // Add context about the cached CVE
              nvdContext = `

=== CACHED CVE DATA (USE THIS AS SOURCE OF TRUTH) ===
CVE ID: ${resolved.cve_id}
This CVE has a verified, cached Dockerfile in our registry.
${resolved.exploit_hint ? `\nExploit Hint: ${resolved.exploit_hint}` : ""}

Use this information to create the recipe. The Dockerfile generation will use the cached version.
===`;
            }
          }

          // If not in cache, try to fetch NVD metadata for CVE IDs
          if (!cachedCveInfo && cveMatch) {
            const cveId = cveMatch[0].toUpperCase();
            const nvdResponse = await fetch(`${octoLabBaseUrl}/cve-registry/${cveId}/metadata`);

            if (nvdResponse.ok) {
              const nvdData = await nvdResponse.json() as NVDMetadata;
              console.log(`[Chat] Fetched NVD metadata for ${cveId}: CVSS ${nvdData.cvss_score}`);

              nvdContext = `

=== OFFICIAL CVE DATA FROM NVD (USE THIS AS SOURCE OF TRUTH) ===
CVE ID: ${nvdData.cve_id}
CVSS Score: ${nvdData.cvss_score ?? "N/A"} (${nvdData.cvss_severity ?? "Unknown"})

OFFICIAL DESCRIPTION (DO NOT HALLUCINATE - USE THIS EXACTLY):
${nvdData.description}

Affected Products:
${nvdData.affected_products.slice(0, 5).map((p) => `- ${p.cpe}`).join("\n") || "See NVD for details"}

References:
${nvdData.references.slice(0, 3).join("\n")}

IMPORTANT: Use the description and affected products above. Do NOT make up information about this CVE.
===`;
            } else {
              console.log(`[Chat] NVD metadata not found for ${cveId}, LLM will use training data`);
            }
          }
        } catch (resolveError) {
          console.warn(`[Chat] Failed to resolve reference '${reference}':`, resolveError);
        }
      }

      // Add user message to conversation (with NVD context if available)
      const enrichedMessage = nvdContext ? `${input.message}${nvdContext}` : input.message;
      ConversationManager.addMessage(conversation.id, {
        role: "user",
        content: enrichedMessage,
      });

      // Get messages for LLM (includes system prompt)
      const messages = ConversationManager.getMessagesForLLM(
        conversation.id,
        RECIPE_SYSTEM_PROMPT
      );

      try {
        // Call LLM with tools
        const response = await llm.chat(messages, {
          tools: recipeTools,
          temperature: 0.7,
          maxTokens: 2048,
        });

        // Handle tool calls
        if (response.toolCalls?.length) {
          const toolCall = response.toolCalls[0];
          const result = formatToolCallResult(
            toolCall.name,
            toolCall.arguments
          );

          // Add assistant message to conversation
          ConversationManager.addMessage(conversation.id, {
            role: "assistant",
            content: result.message,
          });

          // Format response based on action type
          if (result.action === "recipe" && result.recipe) {
            return {
              message: result.message,
              recipe: {
                name: result.recipe.name,
                description: result.recipe.description,
                software: result.recipe.software,
                version_constraint: result.recipe.versionConstraint ?? null,
                exploit_family: result.recipe.exploitFamily ?? null,
                is_active: true,
              },
              confidence: result.recipe.confidence,
              suggestions: result.suggestions ?? [],
              conversationId: conversation.id,
            };
          }

          return {
            message: result.message,
            recipe: null,
            suggestions: result.suggestions ?? [],
            conversationId: conversation.id,
          };
        }

        // Regular chat response (no tool call)
        ConversationManager.addMessage(conversation.id, {
          role: "assistant",
          content: response.content,
        });

        return {
          message: response.content,
          recipe: null,
          suggestions: [],
          conversationId: conversation.id,
        };
      } catch (error) {
        console.error("LLM chat error:", error);

        // Add error context to response
        const errorMessage =
          "I encountered an issue processing your request. Please try again or rephrase your question.";

        return {
          message: errorMessage,
          recipe: null,
          suggestions: [
            "Apache CVE-2021-41773",
            "Log4Shell vulnerability",
            "SQL Injection",
          ],
          conversationId: conversation.id,
        };
      }
    }),

  /**
   * Create a new recipe from parsed intent
   */
  create: protectedProcedure
    .input(recipeCreateSchema)
    .mutation(async ({ ctx, input }) => {
      const recipe = await ctx.prisma.recipe.create({
        data: {
          name: input.name,
          description: input.description,
          software: input.software,
          versionConstraint: input.version_constraint,
          exploitFamily: input.exploit_family,
          isActive: input.is_active ?? true,
        },
      });

      return {
        success: true,
        recipe: {
          id: recipe.id,
          name: recipe.name,
          description: recipe.description,
          software: recipe.software,
          version_constraint: recipe.versionConstraint,
          exploit_family: recipe.exploitFamily,
          is_active: recipe.isActive,
          created_at: recipe.createdAt.toISOString(),
          updated_at: recipe.updatedAt.toISOString(),
        },
      };
    }),

  /**
   * List all recipes
   */
  list: protectedProcedure.query(async ({ ctx }) => {
    const recipes = await ctx.prisma.recipe.findMany({
      where: { isActive: true },
      orderBy: { createdAt: "desc" },
    });

    return recipes.map((r) => ({
      id: r.id,
      name: r.name,
      description: r.description,
      software: r.software,
      version_constraint: r.versionConstraint,
      exploit_family: r.exploitFamily,
      is_active: r.isActive,
      created_at: r.createdAt.toISOString(),
      updated_at: r.updatedAt.toISOString(),
    }));
  }),

  /**
   * Deploy a lab from recipe
   * This creates the recipe, generates Dockerfile, and initiates lab deployment
   */
  deploy: protectedProcedure
    .input(recipeCreateSchema)
    .mutation(async ({ ctx, input }) => {
      // Create or find existing recipe
      let recipe = await ctx.prisma.recipe.findFirst({
        where: { name: input.name },
      });

      if (!recipe) {
        recipe = await ctx.prisma.recipe.create({
          data: {
            name: input.name,
            description: input.description,
            software: input.software,
            versionConstraint: input.version_constraint,
            exploitFamily: input.exploit_family,
            isActive: true,
          },
        });
      }

      // NOTE: Dockerfile generation has been moved to generateDockerfile procedure
      // which includes test-build validation. If recipe has no dockerfile,
      // deployment will fail gracefully below with "No Dockerfile generated" error.

      // OctoLab MVP backend URL (server-to-server)
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://34.151.112.15:8000";
      // Public URL for browser-facing connection URLs
      const publicOctoLabUrl = process.env.NEXT_PUBLIC_OCTOLAB_URL ?? octoLabBaseUrl;

      // Call OctoLab MVP backend to deploy the lab with Dockerfile
      let backendLabId: string | null = null;
      let backendLabStatus = "provisioning";
      let deployError: string | null = null;

      if (recipe.dockerfile) {
        try {
          // Prepare source files in the format expected by the backend
          const sourceFiles = (recipe.sourceFiles as Array<{ filename: string; content: string }>) ?? [];

          const response = await fetch(`${octoLabBaseUrl}/labs/deploy-from-dockerfile`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              // Service token auth for internal frontend-to-backend calls
              ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                "X-User-Email": ctx.session.user.email ?? "",
              }),
            },
            body: JSON.stringify({
              dockerfile: recipe.dockerfile,
              source_files: sourceFiles.map((sf) => ({
                filename: sf.filename,
                content: sf.content,
              })),
              recipe_name: recipe.name,
              software: recipe.software,
              version_constraint: recipe.versionConstraint,
              exploit_family: recipe.exploitFamily,
              base_image: recipe.baseImage,
              exposed_ports: recipe.exposedPorts ?? [],
            }),
          });

          if (response.ok) {
            const labData = await response.json();
            backendLabId = labData.id;
            backendLabStatus = labData.status ?? "provisioning";
            console.log(`Lab deployed to OctoLab MVP: ${backendLabId}`);
          } else if (response.status === 429) {
            // Quota exceeded - throw special error for frontend to handle
            const errorData = await response.json().catch(() => ({ detail: "Lab quota exceeded" }));
            console.error("[deploy] Quota exceeded:", errorData.detail);
            throw new TRPCError({
              code: "TOO_MANY_REQUESTS",
              message: "Maximum active labs exceeded. Please terminate existing labs first.",
            });
          } else if (response.status === 400) {
            // Validation error - throw immediately, don't create failed lab
            const errorData = await response.json().catch(() => ({ detail: "Validation failed" }));
            console.error("[deploy] Validation failed:", errorData.detail);
            throw new TRPCError({
              code: "BAD_REQUEST",
              message: "Dockerfile validation failed. Please regenerate.",
            });
          } else {
            const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
            console.error("[deploy] Deploy failed:", errorData.detail, `HTTP ${response.status}`);
            deployError = "Deployment failed";
            backendLabStatus = "failed";
          }
        } catch (error) {
          // Re-throw TRPCErrors (like quota exceeded)
          if (error instanceof TRPCError) {
            throw error;
          }
          console.error("[deploy] Network/internal error:", error);
          deployError = "Deployment failed";
          backendLabStatus = "failed";
        }
      } else {
        // No Dockerfile - auto-generate one
        console.log("[deploy] Recipe has no Dockerfile - auto-generating...");

        // First check CVE registry for cached Dockerfile
        const cvePattern = /CVE-\d{4}-\d{4,}/i;
        const cveMatch = input.name.match(cvePattern) || input.exploit_family?.match(cvePattern);
        const cveId = cveMatch?.[0]?.toUpperCase();

        let dockerfileGenerated = false;

        if (cveId) {
          try {
            // Try to get cached Dockerfile from registry
            const registryResponse = await fetch(`${octoLabBaseUrl}/cve-registry/${cveId}`, {
              headers: {
                ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                  "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                }),
              },
            });

            if (registryResponse.ok) {
              const cached = await registryResponse.json();
              console.log(`[deploy] Using cached Dockerfile for ${cveId}`);

              // Update recipe with cached Dockerfile
              recipe = await ctx.prisma.recipe.update({
                where: { id: recipe.id },
                data: {
                  dockerfile: cached.dockerfile,
                  sourceFiles: cached.source_files ?? [],
                  baseImage: cached.base_image,
                  exposedPorts: cached.exposed_ports ?? [],
                  vulnerabilityNotes: cached.exploit_hint,
                  dockerfileGeneratedAt: new Date(),
                },
              });
              dockerfileGenerated = true;
            }
          } catch (cacheError) {
            console.warn(`[deploy] CVE registry lookup failed for ${cveId}:`, cacheError);
          }
        }

        if (!dockerfileGenerated) {
          // No cached Dockerfile - need to use LLM generation
          console.error("[deploy] No cached Dockerfile found - LLM generation required");
          throw new TRPCError({
            code: "PRECONDITION_FAILED",
            message: `No cached Dockerfile for this CVE. Please use the "Generate Dockerfile" step first, or wait for LLM generation.`,
          });
        }

        // Now deploy with the cached Dockerfile
        try {
          const sourceFiles = (recipe.sourceFiles as Array<{ filename: string; content: string }>) ?? [];

          const response = await fetch(`${octoLabBaseUrl}/labs/deploy-from-dockerfile`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                "X-User-Email": ctx.session.user.email ?? "",
              }),
            },
            body: JSON.stringify({
              dockerfile: recipe.dockerfile,
              source_files: sourceFiles.map((sf) => ({
                filename: sf.filename,
                content: sf.content,
              })),
              recipe_name: recipe.name,
              software: recipe.software,
              version_constraint: recipe.versionConstraint,
              exploit_family: recipe.exploitFamily,
              base_image: recipe.baseImage,
              exposed_ports: recipe.exposedPorts ?? [],
            }),
          });

          if (response.ok) {
            const labData = await response.json();
            backendLabId = labData.id;
            backendLabStatus = labData.status ?? "provisioning";
            console.log(`[deploy] Lab deployed from cached Dockerfile: ${backendLabId}`);
          } else if (response.status === 429) {
            const errorData = await response.json().catch(() => ({ detail: "Lab quota exceeded" }));
            throw new TRPCError({
              code: "TOO_MANY_REQUESTS",
              message: "Maximum active labs exceeded. Please terminate existing labs first.",
            });
          } else {
            const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
            console.error("[deploy] Deploy from cache failed:", errorData.detail);
            deployError = "Deployment failed";
            backendLabStatus = "failed";
          }
        } catch (error) {
          if (error instanceof TRPCError) {
            throw error;
          }
          console.error("[deploy] Network error deploying from cache:", error);
          deployError = "Deployment failed";
          backendLabStatus = "failed";
        }
      }

      // Create local lab entry tracking the backend lab
      const lab = await ctx.prisma.lab.create({
        data: {
          ownerId: ctx.session.user.id,
          recipeId: recipe.id,
          status: backendLabStatus,
          connectionUrl: backendLabId ? `${publicOctoLabUrl}/labs/${backendLabId}/connect` : null,
          backendLabId: backendLabId ?? null,
        },
      });

      // If deployment succeeded, poll for status updates in the background
      if (backendLabId && backendLabStatus === "provisioning") {
        // Background polling to update local lab status
        const pollStatus = async () => {
          try {
            const statusResponse = await fetch(`${octoLabBaseUrl}/labs/${backendLabId}`, {
              headers: {
                // Use same service token auth as deploy
                ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                  "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                  "X-User-Email": ctx.session.user.email ?? "",
                }),
              },
            });

            if (statusResponse.ok) {
              const statusData = await statusResponse.json();
              if (statusData.status === "ready" || statusData.status === "degraded" || statusData.status === "failed") {
                await ctx.prisma.lab.update({
                  where: { id: lab.id },
                  data: {
                    status: statusData.status,
                    connectionUrl: (statusData.status === "ready" || statusData.status === "degraded")
                      ? `${publicOctoLabUrl}/labs/${backendLabId}/connect`
                      : null,
                  },
                });
              } else {
                // Still provisioning, poll again in 5 seconds
                setTimeout(pollStatus, 5000);
              }
            }
          } catch (e) {
            console.error("Failed to poll lab status:", e);
          }
        };

        // Start polling after initial delay
        setTimeout(pollStatus, 5000);
      }

      return {
        success: !deployError,
        lab: {
          id: lab.id,
          backend_lab_id: backendLabId,
          status: lab.status,
          recipe_id: recipe.id,
          recipe_name: recipe.name,
        },
        dockerfile_generated: !!recipe.dockerfile,
        message: deployError
          ? `Lab deployment failed: ${deployError}`
          : `Lab deployment initiated for "${recipe.name}". ${recipe.dockerfile ? "Dockerfile generated." : ""} It will be ready in a few moments.`,
        error: deployError,
      };
    }),

  /**
   * Get lab status
   */
  labStatus: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .query(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
        include: { recipe: true },
      });

      if (!lab) {
        return null;
      }

      return {
        id: lab.id,
        status: lab.status,
        connection_url: lab.connectionUrl,
        recipe_name: lab.recipe.name,
        created_at: lab.createdAt.toISOString(),
      };
    }),

  /**
   * Get user's active labs
   */
  myLabs: protectedProcedure.query(async ({ ctx }) => {
    const labs = await ctx.prisma.lab.findMany({
      where: {
        ownerId: ctx.session.user.id,
        status: { in: ["provisioning", "ready"] },
      },
      include: { recipe: true },
      orderBy: { createdAt: "desc" },
    });

    return labs.map((lab) => ({
      id: lab.id,
      status: lab.status,
      connection_url: lab.connectionUrl,
      recipe_name: lab.recipe.name,
      recipe_software: lab.recipe.software,
      created_at: lab.createdAt.toISOString(),
    }));
  }),

  /**
   * Clear conversation history
   */
  clearConversation: protectedProcedure
    .input(z.object({ conversationId: z.string() }))
    .mutation(({ input }) => {
      ConversationManager.clear(input.conversationId);
      return { success: true };
    }),

  /**
   * Get LLM provider status (for debugging)
   */
  llmStatus: protectedProcedure.query(async () => {
    const llm = getLLMManager();
    return llm.getStatus();
  }),

  /**
   * Create a recipe without deploying
   * Used when user wants to generate dockerfile first
   */
  createRecipe: protectedProcedure
    .input(recipeCreateSchema)
    .mutation(async ({ ctx, input }) => {
      // Check if recipe already exists
      let recipe = await ctx.prisma.recipe.findFirst({
        where: { name: input.name },
      });

      if (!recipe) {
        recipe = await ctx.prisma.recipe.create({
          data: {
            name: input.name,
            description: input.description,
            software: input.software,
            versionConstraint: input.version_constraint,
            exploitFamily: input.exploit_family,
            isActive: true,
          },
        });
      }

      return {
        id: recipe.id,
        name: recipe.name,
        hasDockerfile: !!recipe.dockerfile,
      };
    }),

  /**
   * Generate Dockerfile for a recipe using LLM
   * Stage 2 of the pipeline: Recipe → Dockerfile
   */
  generateDockerfile: protectedProcedure
    .input(z.object({ recipeId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const llm = getLLMManager();

      // Get the recipe
      const recipe = await ctx.prisma.recipe.findUnique({
        where: { id: input.recipeId },
      });

      if (!recipe) {
        throw new Error("Recipe not found");
      }

      // Check if dockerfile already generated
      if (recipe.dockerfile) {
        return {
          success: true,
          alreadyGenerated: true,
          dockerfile: recipe.dockerfile,
          sourceFiles: recipe.sourceFiles as Array<{ filename: string; content: string }> | null,
          baseImage: recipe.baseImage,
          exposedPorts: recipe.exposedPorts,
          entrypoint: recipe.entrypoint,
          vulnerabilityNotes: recipe.vulnerabilityNotes,
        };
      }

      // Check CVE registry cache before calling LLM
      const cvePattern = /CVE-\d{4}-\d{4,}/i;
      const cveMatch = recipe.name.match(cvePattern) || recipe.exploitFamily?.match(cvePattern);
      const cveId = cveMatch?.[0]?.toUpperCase();

      if (cveId) {
        try {
          const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";
          const registryResponse = await fetch(`${octoLabBaseUrl}/cve-registry/${cveId}`, {
            headers: {
              ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
              }),
            },
          });

          if (registryResponse.ok) {
            const cached = await registryResponse.json();
            console.log(`[CVE Registry] Using cached Dockerfile for ${cveId}`);

            // Update recipe with cached Dockerfile
            const updatedRecipe = await ctx.prisma.recipe.update({
              where: { id: recipe.id },
              data: {
                dockerfile: cached.dockerfile,
                sourceFiles: cached.source_files ?? [],
                baseImage: cached.base_image,
                exposedPorts: cached.exposed_ports ?? [],
                vulnerabilityNotes: cached.exploit_hint,
                dockerfileGeneratedAt: new Date(),
              },
            });

            return {
              success: true,
              fromCache: true,
              dockerfile: updatedRecipe.dockerfile,
              sourceFiles: updatedRecipe.sourceFiles as Array<{ filename: string; content: string }> | null,
              baseImage: updatedRecipe.baseImage,
              exposedPorts: updatedRecipe.exposedPorts,
              entrypoint: updatedRecipe.entrypoint,
              vulnerabilityNotes: updatedRecipe.vulnerabilityNotes,
            };
          }
        } catch (error) {
          console.warn(`[CVE Registry] Lookup failed for ${cveId}:`, error);
          // Fall through to LLM generation
        }
      }

      // Retry loop with error context (5 attempts to handle build/runtime errors)
      const MAX_RETRIES = 5;
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";
      const previousAttempts: Array<{
        dockerfile: string;
        error: string;
        confidence?: number;
        confidenceReason?: string;
      }> = [];

      // Fetch NVD metadata for CVE context (once before retry loop)
      let nvdMetadata: NVDMetadata | null = null;
      if (cveId) {
        try {
          const nvdResponse = await fetch(`${octoLabBaseUrl}/cve-registry/${cveId}/metadata`);
          if (nvdResponse.ok) {
            nvdMetadata = await nvdResponse.json();
            console.log(`[NVD] Fetched metadata for ${cveId}: CVSS ${nvdMetadata?.cvss_score}`);
          }
        } catch (nvdError) {
          console.warn(`[NVD] Failed to fetch metadata for ${cveId}:`, nvdError);
        }
      }

      for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        console.log(`[LLM] Attempt ${attempt}/${MAX_RETRIES} for recipe ${recipe.id}`);

        try {
          // Build prompt with NVD context and error context from previous attempts
          let prompt = buildDockerfilePrompt(
            {
              name: recipe.name,
              description: recipe.description ?? "",
              software: recipe.software,
              versionConstraint: recipe.versionConstraint,
              exploitFamily: recipe.exploitFamily,
            },
            nvdMetadata
          );

          // Add error context if this is a retry
          if (previousAttempts.length > 0) {
            prompt += `\n\n⚠️ IMPORTANT: Previous attempts failed validation. Fix these errors:\n\n`;
            for (const [i, prev] of previousAttempts.entries()) {
              prompt += `Attempt ${i + 1} error: ${prev.error}\n`;
            }
            prompt += `\nGenerate a FIXED Dockerfile that addresses these validation errors.\n`;
            prompt += `Common fixes:\n`;
            prompt += `- If COPY references a file, include it in sourceFiles array\n`;
            prompt += `- Ensure all syntax is valid\n`;
            prompt += `- Do not use dangerous patterns (rm -rf /, curl|sh)\n`;
          }

          // Call LLM with Dockerfile generation tools
          const response = await llm.chat(
            [
              { role: "system", content: DOCKERFILE_SYSTEM_PROMPT },
              { role: "user", content: prompt },
            ],
            {
              tools: dockerfileTools,
              temperature: 0.3 + (attempt - 1) * 0.1, // Slightly increase temperature on retries
              maxTokens: 4096,
            }
          );

          // Handle tool call response
          if (!response.toolCalls?.length) {
            previousAttempts.push({
              dockerfile: "",
              error: "LLM did not generate a Dockerfile",
            });
            continue;
          }

          const toolCall = response.toolCalls[0];
          const args = toolCall.arguments as {
            dockerfile: string;
            sourceFiles: Array<{ filename: string; content: string }>;
            baseImage: string;
            exposedPorts: number[];
            entrypoint: string;
            vulnerabilityNotes: string;
            confidence: number;
            confidenceReason: string;
          };

          // Check confidence before attempting validation
          const confidence = args.confidence ?? 50; // Default to medium if not provided
          const confidenceReason = args.confidenceReason ?? "No reason provided";

          // Low confidence (<30%) - skip retries, go directly to review queue
          if (confidence < 30) {
            console.log(`[LLM] Low confidence (${confidence}%) for ${cveId || recipe.name}, skipping to review queue`);
            console.log(`[LLM] Reason: ${confidenceReason}`);

            if (cveId) {
              try {
                await fetch(`${octoLabBaseUrl}/dockerfile-review-queue/`, {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json",
                    ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                      "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                      "X-User-Email": ctx.session.user.email ?? "system@octolab",
                    }),
                  },
                  body: JSON.stringify({
                    cve_id: cveId,
                    recipe_name: recipe.name,
                    last_dockerfile: args.dockerfile,
                    errors: [`Low confidence (${confidence}%): ${confidenceReason}`],
                    attempts: 1,
                    confidence_score: confidence,
                    confidence_reason: confidenceReason,
                  }),
                });
                console.log(`[Review Queue] Added ${cveId} for manual review (low confidence)`);
              } catch (queueError) {
                console.warn(`[Review Queue] Failed to queue ${cveId}:`, queueError);
              }
            }

            console.warn(`[LLM] Low confidence (${confidence}%) for ${cveId}: ${confidenceReason}`);
            throw new Error(
              "Unable to generate a reliable Dockerfile for this CVE. Added to review queue for manual verification."
            );
          }

          // Validate against backend before saving
          const validationResponse = await fetch(`${octoLabBaseUrl}/labs/validate-dockerfile`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                "X-User-Email": ctx.session.user.email ?? "",
              }),
            },
            body: JSON.stringify({
              dockerfile: args.dockerfile,
              source_files: args.sourceFiles?.map((sf) => ({
                filename: sf.filename,
                content: sf.content,
              })) ?? [],
              recipe_name: recipe.name,
              software: recipe.software ?? "unknown",
            }),
          });

          const validation = await validationResponse.json();

          if (!validation.valid) {
            const errorMsg = validation.errors?.join("; ") ?? "Validation failed";
            console.warn(`[LLM] Attempt ${attempt} validation failed: ${errorMsg}`);
            previousAttempts.push({
              dockerfile: args.dockerfile,
              error: errorMsg,
              confidence,
              confidenceReason,
            });
            continue;
          }

          // Syntax validation passed - now test-build to catch runtime issues
          console.log(`[LLM] Syntax valid, testing build for attempt ${attempt}`);
          const testBuildResponse = await fetch(`${octoLabBaseUrl}/labs/test-build`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                "X-User-Email": ctx.session.user.email ?? "",
              }),
            },
            body: JSON.stringify({
              dockerfile: args.dockerfile,
              source_files: args.sourceFiles?.map((sf) => ({
                filename: sf.filename,
                content: sf.content,
              })) ?? [],
            }),
          });

          const testBuild = await testBuildResponse.json();

          if (!testBuild.success) {
            const buildError = testBuild.error ?? "Build test failed";
            console.warn(`[LLM] Attempt ${attempt} build test failed: ${buildError}`);
            previousAttempts.push({
              dockerfile: args.dockerfile,
              error: `Build/runtime error: ${buildError}`,
              confidence,
              confidenceReason,
            });

            // Clean up test container if one was created
            if (testBuild.container_id) {
              try {
                await fetch(`${octoLabBaseUrl}/labs/test-build/${testBuild.container_id}`, {
                  method: "DELETE",
                  headers: {
                    ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                      "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                      "X-User-Email": ctx.session.user.email ?? "system@octolab",
                    }),
                  },
                });
              } catch (cleanupErr) {
                console.warn(`[LLM] Failed to cleanup test container:`, cleanupErr);
              }
            }
            continue;
          }

          // Clean up successful test container
          if (testBuild.container_id) {
            try {
              await fetch(`${octoLabBaseUrl}/labs/test-build/${testBuild.container_id}`, {
                method: "DELETE",
                headers: {
                  ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                    "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                    "X-User-Email": ctx.session.user.email ?? "system@octolab",
                  }),
                },
              });
            } catch (cleanupErr) {
              console.warn(`[LLM] Failed to cleanup test container:`, cleanupErr);
            }
          }

          // Validation AND build test passed - save and return
          console.log(`[LLM] Success on attempt ${attempt} for recipe ${recipe.id}`);

          // Update recipe with generated Dockerfile and source files
          const updatedRecipe = await ctx.prisma.recipe.update({
            where: { id: recipe.id },
            data: {
              dockerfile: args.dockerfile,
              sourceFiles: args.sourceFiles ?? [],
              baseImage: args.baseImage,
              exposedPorts: args.exposedPorts,
              entrypoint: args.entrypoint,
              vulnerabilityNotes: args.vulnerabilityNotes,
              dockerfileGeneratedAt: new Date(),
            },
          });

          // Cache to CVE registry if this is a CVE-based recipe
          if (cveId) {
            try {
              const cacheResponse = await fetch(`${octoLabBaseUrl}/cve-registry/`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                    "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                    "X-User-Email": ctx.session.user.email ?? "system@octolab",
                  }),
                },
                body: JSON.stringify({
                  cve_id: cveId,
                  dockerfile: args.dockerfile,
                  source_files: args.sourceFiles ?? [],
                  base_image: args.baseImage,
                  exposed_ports: args.exposedPorts ?? [],
                  exploit_hint: args.vulnerabilityNotes,
                  status: "llm_validated",
                  confidence_score: confidence,
                  confidence_reason: confidenceReason,
                }),
              });
              if (cacheResponse.ok) {
                console.log(`[CVE Registry] Cached validated Dockerfile for ${cveId} (confidence: ${confidence}%)`);
              } else {
                console.warn(`[CVE Registry] Failed to cache ${cveId}: HTTP ${cacheResponse.status}`);
              }
            } catch (cacheError) {
              // Non-fatal - log and continue
              console.warn(`[CVE Registry] Failed to cache ${cveId}:`, cacheError);
            }
          }

          return {
            success: true,
            alreadyGenerated: false,
            dockerfile: updatedRecipe.dockerfile,
            sourceFiles: updatedRecipe.sourceFiles as Array<{ filename: string; content: string }> | null,
            baseImage: updatedRecipe.baseImage,
            exposedPorts: updatedRecipe.exposedPorts,
            entrypoint: updatedRecipe.entrypoint,
            vulnerabilityNotes: updatedRecipe.vulnerabilityNotes,
          };
        } catch (error) {
          const errorMsg = error instanceof Error ? error.message : String(error);
          console.error(`[LLM] Attempt ${attempt} error:`, errorMsg);
          previousAttempts.push({
            dockerfile: "",
            error: errorMsg,
          });
        }
      }

      // All retries failed - add to review queue
      console.error(`[LLM] All ${MAX_RETRIES} attempts failed for recipe ${recipe.id}`);

      // Get confidence from the last attempt if available
      const lastAttempt = previousAttempts.at(-1);
      const lastConfidence = lastAttempt?.confidence ?? null;
      const lastConfidenceReason = lastAttempt?.confidenceReason ?? null;

      if (cveId) {
        try {
          await fetch(`${octoLabBaseUrl}/dockerfile-review-queue/`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(process.env.OCTOLAB_SERVICE_TOKEN && {
                "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
                "X-User-Email": ctx.session.user.email ?? "system@octolab",
              }),
            },
            body: JSON.stringify({
              cve_id: cveId,
              recipe_name: recipe.name,
              last_dockerfile: lastAttempt?.dockerfile ?? "",
              errors: previousAttempts.map((a) => a.error),
              attempts: previousAttempts.length,
              confidence_score: lastConfidence,
              confidence_reason: lastConfidenceReason,
            }),
          });
          console.log(`[Review Queue] Added ${cveId} for manual review`);
        } catch (queueError) {
          console.warn(`[Review Queue] Failed to queue ${cveId}:`, queueError);
        }
      }

      const lastError = previousAttempts.at(-1)?.error ?? "Unknown error";
      console.error(`[LLM] All ${MAX_RETRIES} attempts failed. Last error: ${lastError}`);
      throw new Error(
        `Failed to generate valid Dockerfile after ${MAX_RETRIES} attempts. Please try again or contact support.`
      );
    }),

  /**
   * Get recipe with Dockerfile
   */
  getWithDockerfile: protectedProcedure
    .input(z.object({ recipeId: z.string() }))
    .query(async ({ ctx, input }) => {
      const recipe = await ctx.prisma.recipe.findUnique({
        where: { id: input.recipeId },
      });

      if (!recipe) {
        return null;
      }

      return {
        id: recipe.id,
        name: recipe.name,
        description: recipe.description,
        software: recipe.software,
        version_constraint: recipe.versionConstraint,
        exploit_family: recipe.exploitFamily,
        dockerfile: recipe.dockerfile,
        source_files: recipe.sourceFiles as Array<{ filename: string; content: string }> | null,
        base_image: recipe.baseImage,
        exposed_ports: recipe.exposedPorts,
        entrypoint: recipe.entrypoint,
        vulnerability_notes: recipe.vulnerabilityNotes,
        dockerfile_generated_at: recipe.dockerfileGeneratedAt?.toISOString() ?? null,
      };
    }),

  /**
   * Update Dockerfile for a recipe (admin only)
   * Used by lab report review to fix broken Dockerfiles
   */
  updateDockerfile: adminProcedure
    .input(
      z.object({
        id: z.string(),
        dockerfile: z.string(),
        sourceFiles: z.array(z.object({
          filename: z.string(),
          content: z.string(),
        })).optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const recipe = await ctx.prisma.recipe.findUnique({
        where: { id: input.id },
      });

      if (!recipe) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Recipe not found",
        });
      }

      const updated = await ctx.prisma.recipe.update({
        where: { id: input.id },
        data: {
          dockerfile: input.dockerfile,
          sourceFiles: input.sourceFiles ?? recipe.sourceFiles,
          dockerfileGeneratedAt: new Date(),
        },
      });

      return {
        success: true,
        recipe: {
          id: updated.id,
          name: updated.name,
          dockerfile: updated.dockerfile,
        },
      };
    }),
});
