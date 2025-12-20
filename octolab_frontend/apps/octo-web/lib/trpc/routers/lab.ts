import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { createTRPCRouter, protectedProcedure } from "../init";

/**
 * Lab status enum
 */
const labStatusSchema = z.enum([
  "requested",
  "provisioning",
  "ready",
  "connecting",
  "connected",
  "stopped",
  "error",
  "expired",
]);

export type LabStatus = z.infer<typeof labStatusSchema>;

export const labRouter = createTRPCRouter({
  /**
   * Get lab status by ID
   */
  getStatus: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .query(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
        include: {
          recipe: {
            select: {
              id: true,
              name: true,
              software: true,
              description: true,
              exploitFamily: true,
              exposedPorts: true,
              vulnerabilityNotes: true,
            },
          },
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      return {
        id: lab.id,
        status: lab.status as LabStatus,
        connectionUrl: lab.connectionUrl,
        expiresAt: lab.expiresAt?.toISOString() ?? null,
        createdAt: lab.createdAt.toISOString(),
        updatedAt: lab.updatedAt.toISOString(),
        recipe: {
          id: lab.recipe.id,
          name: lab.recipe.name,
          software: lab.recipe.software,
          description: lab.recipe.description,
          exploitFamily: lab.recipe.exploitFamily,
          exposedPorts: lab.recipe.exposedPorts,
          vulnerabilityNotes: lab.recipe.vulnerabilityNotes,
        },
      };
    }),

  /**
   * Get connection details for a lab
   */
  getConnection: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .query(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
        include: {
          recipe: {
            select: {
              name: true,
              software: true,
              exposedPorts: true,
            },
          },
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status !== "ready" && lab.status !== "connected") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: `Lab is not ready. Current status: ${lab.status}`,
        });
      }

      // OctoLab MVP backend URL
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://34.151.112.15";

      // Connection details - the lab page on OctoLab MVP will provide the Guacamole/OctoBox URL
      const connectionDetails = {
        id: lab.id,
        status: lab.status,
        recipeName: lab.recipe.name,
        software: lab.recipe.software,
        // Main lab page URL where user can access OctoBox
        labPageUrl: lab.connectionUrl ?? `${octoLabBaseUrl}/labs/${lab.id}`,
        // OctoBox/Guacamole URL will be fetched from OctoLab MVP when lab is ready
        octoBoxUrl: lab.status === "ready" ? `${octoLabBaseUrl}/guacamole/#/client/${lab.id}` : null,
        exposedPorts: lab.recipe.exposedPorts,
        expiresAt: lab.expiresAt?.toISOString() ?? null,
      };

      return connectionDetails;
    }),

  /**
   * Connect to a lab (marks it as connecting/connected)
   */
  connect: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status !== "ready" && lab.status !== "connected") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: `Cannot connect to lab. Current status: ${lab.status}`,
        });
      }

      // Update lab status to connected
      const updatedLab = await ctx.prisma.lab.update({
        where: { id: lab.id },
        data: {
          status: "connected",
          updatedAt: new Date(),
        },
      });

      return {
        success: true,
        labId: updatedLab.id,
        status: updatedLab.status,
        connectionUrl: updatedLab.connectionUrl ?? `https://lab.octolab.dev/${lab.id}`,
        message: "Connected to lab successfully",
      };
    }),

  /**
   * Disconnect from a lab (keeps it running)
   */
  disconnect: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status !== "connected") {
        return {
          success: true,
          labId: lab.id,
          status: lab.status,
          message: "Lab was not connected",
        };
      }

      const updatedLab = await ctx.prisma.lab.update({
        where: { id: lab.id },
        data: {
          status: "ready",
          updatedAt: new Date(),
        },
      });

      return {
        success: true,
        labId: updatedLab.id,
        status: updatedLab.status,
        message: "Disconnected from lab",
      };
    }),

  /**
   * Stop/terminate a lab
   * Supports both frontend Prisma lab IDs and backend lab IDs (UUIDs)
   */
  stop: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://localhost:8000";

      const authHeaders: Record<string, string> = {};
      if (process.env.OCTOLAB_SERVICE_TOKEN) {
        authHeaders["X-Service-Token"] = process.env.OCTOLAB_SERVICE_TOKEN;
        authHeaders["X-User-Email"] = ctx.session.user.email ?? "";
      }

      // Try to find the lab in Prisma first (for labs created through frontend)
      const prismaLab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      // Determine the backend lab ID
      let backendLabId: string;
      let hasPrismaRecord = false;

      if (prismaLab) {
        hasPrismaRecord = true;
        // Already in terminal state
        if (prismaLab.status === "stopped" || prismaLab.status === "expired" || prismaLab.status === "error") {
          return {
            success: true,
            labId: prismaLab.id,
            status: prismaLab.status,
            message: "Lab is already stopped",
          };
        }

        // Get backend lab ID from Prisma record
        backendLabId = prismaLab.backendLabId ?? "";
        if (!backendLabId && prismaLab.connectionUrl) {
          const match = prismaLab.connectionUrl.match(/\/labs\/([a-f0-9-]+)\/connect/i);
          if (match) {
            backendLabId = match[1];
          }
        }

        // No backend lab ID - just update local status
        if (!backendLabId) {
          console.warn(`Lab ${prismaLab.id} has no backend lab ID - updating local status only`);
          const updatedLab = await ctx.prisma.lab.update({
            where: { id: prismaLab.id },
            data: { status: "stopped", updatedAt: new Date() },
          });
          return {
            success: true,
            labId: updatedLab.id,
            status: updatedLab.status,
            message: "Lab marked as stopped (no backend lab ID)",
          };
        }
      } else {
        // No Prisma record - assume input.labId IS the backend lab ID (UUID)
        // This happens when stopping labs from quota modal that only exist in backend
        backendLabId = input.labId;

        // Verify the lab exists in backend and belongs to user
        try {
          const verifyResponse = await fetch(`${octoLabBaseUrl}/labs/${backendLabId}`, {
            headers: authHeaders,
          });

          if (!verifyResponse.ok) {
            throw new TRPCError({
              code: "NOT_FOUND",
              message: "Lab not found",
            });
          }

          const backendLab = await verifyResponse.json();
          // Check if already in terminal state
          const backendStatus = backendLab.status?.toLowerCase();
          if (backendStatus === "finished" || backendStatus === "failed") {
            return {
              success: true,
              labId: backendLabId,
              status: backendStatus === "finished" ? "stopped" : "error",
              message: "Lab is already stopped",
            };
          }
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: "NOT_FOUND",
            message: "Lab not found",
          });
        }
      }

      // Step 1: Set local status to "ending" if we have a Prisma record
      if (hasPrismaRecord && prismaLab) {
        await ctx.prisma.lab.update({
          where: { id: prismaLab.id },
          data: { status: "ending", updatedAt: new Date() },
        });
      }

      // Step 2: Call backend to initiate stop (DELETE marks as ENDING, teardown worker handles rest)
      try {
        const stopResponse = await fetch(`${octoLabBaseUrl}/labs/${backendLabId}`, {
          method: "DELETE",
          headers: { ...authHeaders },
        });

        if (!stopResponse.ok) {
          const errorData = await stopResponse.json().catch(() => ({}));
          throw new Error(errorData.detail ?? `Backend returned ${stopResponse.status}`);
        }
      } catch (error) {
        // Backend call failed - mark as error if we have Prisma record
        const errorMessage = error instanceof Error ? error.message : "Network error";
        console.error("Backend stop failed:", errorMessage);

        if (hasPrismaRecord && prismaLab) {
          const updatedLab = await ctx.prisma.lab.update({
            where: { id: prismaLab.id },
            data: { status: "error", updatedAt: new Date() },
          });
          return {
            success: false,
            labId: updatedLab.id,
            status: updatedLab.status,
            message: `Failed to stop lab: ${errorMessage}`,
          };
        }
        return {
          success: false,
          labId: backendLabId,
          status: "error",
          message: `Failed to stop lab: ${errorMessage}`,
        };
      }

      // Step 3: Poll backend until terminal state (FINISHED/FAILED) with 60s timeout
      const POLL_INTERVAL_MS = 1000;
      const TIMEOUT_MS = 60000;
      const startTime = Date.now();
      let finalStatus = "ending";

      while (Date.now() - startTime < TIMEOUT_MS) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));

        try {
          const statusResponse = await fetch(`${octoLabBaseUrl}/labs/${backendLabId}`, {
            headers: authHeaders,
          });

          if (statusResponse.ok) {
            const statusData = await statusResponse.json();
            const backendStatus = statusData.status?.toLowerCase();

            // Terminal states
            if (backendStatus === "finished" || backendStatus === "failed") {
              finalStatus = backendStatus === "finished" ? "stopped" : "error";
              break;
            }
          }
        } catch (e) {
          console.warn("Error polling lab status:", e);
          // Continue polling on transient errors
        }
      }

      // Step 4: Update local status to terminal state (if we have Prisma record)
      const terminalStatus = finalStatus === "ending" ? "error" : finalStatus; // Timeout = error

      if (hasPrismaRecord && prismaLab) {
        const updatedLab = await ctx.prisma.lab.update({
          where: { id: prismaLab.id },
          data: { status: terminalStatus, updatedAt: new Date() },
        });

        const timedOut = finalStatus === "ending";
        return {
          success: !timedOut && terminalStatus === "stopped",
          labId: updatedLab.id,
          status: updatedLab.status,
          message: timedOut
            ? "Lab teardown taking too long. Contact support."
            : terminalStatus === "stopped"
              ? "Lab stopped successfully"
              : "Lab teardown failed",
        };
      }

      // No Prisma record - return backend-only result
      const timedOut = finalStatus === "ending";
      return {
        success: !timedOut && terminalStatus === "stopped",
        labId: backendLabId,
        status: terminalStatus,
        message: timedOut
          ? "Lab teardown taking too long. Contact support."
          : terminalStatus === "stopped"
            ? "Lab stopped successfully"
            : "Lab teardown failed",
      };
    }),

  /**
   * Restart a stopped lab
   */
  restart: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status === "expired") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: "Cannot restart an expired lab. Please create a new one.",
        });
      }

      // Set to provisioning, then simulate becoming ready
      const updatedLab = await ctx.prisma.lab.update({
        where: { id: lab.id },
        data: {
          status: "provisioning",
          updatedAt: new Date(),
        },
      });

      // TODO: In production, trigger actual restart
      // Simulate restart completion
      setTimeout(async () => {
        try {
          await ctx.prisma.lab.update({
            where: { id: lab.id },
            data: {
              status: "ready",
              expiresAt: new Date(Date.now() + 2 * 60 * 60 * 1000), // 2 hours from now
            },
          });
        } catch (e) {
          console.error("Failed to update lab status after restart:", e);
        }
      }, 3000);

      return {
        success: true,
        labId: updatedLab.id,
        status: updatedLab.status,
        message: "Lab is restarting...",
      };
    }),

  /**
   * Extend lab expiration time
   */
  extend: protectedProcedure
    .input(
      z.object({
        labId: z.string(),
        hours: z.number().min(1).max(24).default(2),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status === "stopped" || lab.status === "expired") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: "Cannot extend a stopped or expired lab",
        });
      }

      const currentExpiry = lab.expiresAt ?? new Date();
      const newExpiry = new Date(
        Math.max(currentExpiry.getTime(), Date.now()) + input.hours * 60 * 60 * 1000
      );

      const updatedLab = await ctx.prisma.lab.update({
        where: { id: lab.id },
        data: {
          expiresAt: newExpiry,
          updatedAt: new Date(),
        },
      });

      return {
        success: true,
        labId: updatedLab.id,
        expiresAt: updatedLab.expiresAt?.toISOString() ?? null,
        message: `Lab extended by ${input.hours} hour(s)`,
      };
    }),

  /**
   * List all user's labs (including stopped)
   */
  list: protectedProcedure
    .input(
      z
        .object({
          status: labStatusSchema.optional(),
          limit: z.number().min(1).max(50).default(20),
          cursor: z.string().optional(),
        })
        .optional()
    )
    .query(async ({ ctx, input }) => {
      const limit = input?.limit ?? 20;
      const cursor = input?.cursor;
      const status = input?.status;

      const labs = await ctx.prisma.lab.findMany({
        where: {
          ownerId: ctx.session.user.id,
          ...(status && { status }),
        },
        include: {
          recipe: {
            select: {
              id: true,
              name: true,
              software: true,
              exploitFamily: true,
            },
          },
        },
        orderBy: { createdAt: "desc" },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
      });

      let nextCursor: string | undefined;
      if (labs.length > limit) {
        const nextItem = labs.pop();
        nextCursor = nextItem?.id;
      }

      return {
        labs: labs.map((lab) => ({
          id: lab.id,
          status: lab.status as LabStatus,
          connectionUrl: lab.connectionUrl,
          expiresAt: lab.expiresAt?.toISOString() ?? null,
          createdAt: lab.createdAt.toISOString(),
          updatedAt: lab.updatedAt.toISOString(),
          recipe: {
            id: lab.recipe.id,
            name: lab.recipe.name,
            software: lab.recipe.software,
            exploitFamily: lab.recipe.exploitFamily,
          },
        })),
        nextCursor,
      };
    }),

  /**
   * Get active labs (provisioning, ready, ending)
   * Fetches from backend API (source of truth) to ensure accurate quota data
   * Includes "ending" to match backend quota check which counts PROVISIONING, READY, ENDING
   */
  listActive: protectedProcedure.query(async ({ ctx }) => {
    const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://localhost:8000";

    const authHeaders: Record<string, string> = {};
    if (process.env.OCTOLAB_SERVICE_TOKEN) {
      authHeaders["X-Service-Token"] = process.env.OCTOLAB_SERVICE_TOKEN;
      authHeaders["X-User-Email"] = ctx.session.user.email ?? "";
    }

    try {
      // Fetch all labs from backend (source of truth)
      // Note: Use trailing slash to avoid 307 redirect which may strip headers
      const response = await fetch(`${octoLabBaseUrl}/labs/`, {
        headers: authHeaders,
      });

      if (!response.ok) {
        console.error(`Backend /labs returned ${response.status}`);
        // Fall back to empty array on error
        return [];
      }

      const backendLabs = await response.json();

      // Filter to active statuses (matching backend quota check)
      const activeStatuses = ["provisioning", "ready", "degraded", "ending"];
      const activeLabs = backendLabs.filter((lab: { status: string }) =>
        activeStatuses.includes(lab.status?.toLowerCase())
      );

      // Map to frontend format
      return activeLabs.map((lab: {
        id: string;
        status: string;
        connection_url?: string;
        expires_at?: string;
        created_at: string;
        recipe_id: string;
        requested_intent?: {
          software?: string;
          version?: string;
          exploit_family?: string;
        };
      }) => ({
        id: lab.id,
        status: lab.status as LabStatus,
        connectionUrl: lab.connection_url ?? null,
        expiresAt: lab.expires_at ?? null,
        createdAt: lab.created_at,
        recipe: {
          id: lab.recipe_id,
          // Use requested_intent for recipe info since backend doesn't include full recipe
          name: lab.requested_intent?.software
            ? `${lab.requested_intent.software}${lab.requested_intent.version ? ` ${lab.requested_intent.version}` : ""}`
            : "Unknown Recipe",
          software: lab.requested_intent?.software ?? "Unknown",
          exploitFamily: lab.requested_intent?.exploit_family ?? null,
          exposedPorts: [],
        },
      }));
    } catch (error) {
      console.error("Failed to fetch labs from backend:", error);
      // Fall back to empty array on network error
      return [];
    }
  }),

  /**
   * Delete a lab (only if stopped)
   */
  delete: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status !== "stopped" && lab.status !== "expired" && lab.status !== "error") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: "Can only delete stopped, expired, or errored labs",
        });
      }

      await ctx.prisma.lab.delete({
        where: { id: lab.id },
      });

      return {
        success: true,
        message: "Lab deleted successfully",
      };
    }),

  /**
   * Get lab statistics for current user
   */
  stats: protectedProcedure.query(async ({ ctx }) => {
    const [total, active, ready, stopped] = await Promise.all([
      ctx.prisma.lab.count({ where: { ownerId: ctx.session.user.id } }),
      ctx.prisma.lab.count({
        where: {
          ownerId: ctx.session.user.id,
          status: { in: ["provisioning", "ready", "connecting", "connected"] },
        },
      }),
      ctx.prisma.lab.count({
        where: { ownerId: ctx.session.user.id, status: "ready" },
      }),
      ctx.prisma.lab.count({
        where: {
          ownerId: ctx.session.user.id,
          status: { in: ["stopped", "expired"] },
        },
      }),
    ]);

    return {
      total,
      active,
      ready,
      stopped,
    };
  }),

  /**
   * Reset lab to initial state (re-provision)
   */
  reset: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const lab = await ctx.prisma.lab.findFirst({
        where: {
          id: input.labId,
          ownerId: ctx.session.user.id,
        },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      if (lab.status === "expired") {
        throw new TRPCError({
          code: "PRECONDITION_FAILED",
          message: "Cannot reset an expired lab. Please create a new one.",
        });
      }

      // Set to provisioning for reset
      const updatedLab = await ctx.prisma.lab.update({
        where: { id: lab.id },
        data: {
          status: "provisioning",
          updatedAt: new Date(),
        },
      });

      // TODO: In production, trigger actual reset
      // Simulate reset completion
      setTimeout(async () => {
        try {
          await ctx.prisma.lab.update({
            where: { id: lab.id },
            data: {
              status: "ready",
              expiresAt: new Date(Date.now() + 2 * 60 * 60 * 1000), // 2 hours from now
            },
          });
        } catch (e) {
          console.error("Failed to update lab status after reset:", e);
        }
      }, 5000);

      return {
        success: true,
        labId: updatedLab.id,
        status: updatedLab.status,
        message: "Lab is being reset to initial state...",
      };
    }),
});
