import { z } from "zod";
import { TRPCError } from "@trpc/server";
import { createTRPCRouter, protectedProcedure, adminProcedure } from "../init";

const issueTypeSchema = z.enum([
  "exploit_fails",
  "wont_start",
  "connection",
  "wrong_version",
  "other",
]);

const reportStatusSchema = z.enum([
  "open",
  "investigating",
  "fixed",
  "wont_fix",
  "duplicate",
]);

const submitReportSchema = z.object({
  labId: z.string(),
  issueType: issueTypeSchema,
  attempted: z.string().min(10, "Please describe what you tried (min 10 chars)").max(2000),
  actual: z.string().min(10, "Please describe what happened (min 10 chars)").max(2000),
  expected: z.string().max(2000).optional(),
  includeLogs: z.boolean().default(false),
});

export const labReportRouter = createTRPCRouter({
  /**
   * Submit a lab report (one per lab per user)
   */
  submit: protectedProcedure
    .input(submitReportSchema)
    .mutation(async ({ ctx, input }) => {
      // Get lab with recipe info
      const lab = await ctx.prisma.lab.findUnique({
        where: { id: input.labId },
        include: { recipe: true },
      });

      if (!lab) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Lab not found",
        });
      }

      // Check if user owns this lab
      if (lab.ownerId !== ctx.session.user.id) {
        throw new TRPCError({
          code: "FORBIDDEN",
          message: "You can only report your own labs",
        });
      }

      // Check if user already reported this lab
      const existingReport = await ctx.prisma.labReport.findUnique({
        where: {
          labId_userId: {
            labId: input.labId,
            userId: ctx.session.user.id,
          },
        },
      });

      if (existingReport) {
        throw new TRPCError({
          code: "CONFLICT",
          message: "You have already reported this lab",
        });
      }

      // Create the report
      const report = await ctx.prisma.labReport.create({
        data: {
          labId: input.labId,
          recipeId: lab.recipeId,
          userId: ctx.session.user.id,
          issueType: input.issueType,
          attempted: input.attempted,
          actual: input.actual,
          expected: input.expected,
          includeLogs: input.includeLogs,
          status: "open",
        },
      });

      return {
        success: true,
        id: report.id,
        message: "Report submitted. Our team will investigate.",
      };
    }),

  /**
   * Check if user has already reported a lab
   */
  hasReported: protectedProcedure
    .input(z.object({ labId: z.string() }))
    .query(async ({ ctx, input }) => {
      const report = await ctx.prisma.labReport.findUnique({
        where: {
          labId_userId: {
            labId: input.labId,
            userId: ctx.session.user.id,
          },
        },
        select: { id: true, status: true },
      });

      return {
        hasReported: !!report,
        reportId: report?.id,
        status: report?.status,
      };
    }),

  /**
   * Get current user's reports
   */
  myReports: protectedProcedure
    .input(
      z.object({
        limit: z.number().min(1).max(50).default(20),
        cursor: z.string().optional(),
      })
    )
    .query(async ({ ctx, input }) => {
      const { limit, cursor } = input;

      const reports = await ctx.prisma.labReport.findMany({
        where: { userId: ctx.session.user.id },
        include: {
          recipe: { select: { id: true, name: true, software: true } },
          lab: { select: { id: true, status: true } },
        },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
        orderBy: { createdAt: "desc" },
      });

      let nextCursor: string | undefined;
      if (reports.length > limit) {
        const nextItem = reports.pop();
        nextCursor = nextItem?.id;
      }

      return { reports, nextCursor };
    }),

  // ============ Admin endpoints ============

  /**
   * List all reports (admin only)
   * Groups by recipe for easy triage
   */
  list: adminProcedure
    .input(
      z.object({
        status: reportStatusSchema.optional(),
        limit: z.number().min(1).max(100).default(50),
      })
    )
    .query(async ({ ctx, input }) => {
      const { status, limit } = input;

      // Get reports grouped by recipe
      const reports = await ctx.prisma.labReport.findMany({
        where: {
          ...(status && { status }),
        },
        include: {
          recipe: { select: { id: true, name: true, software: true, dockerfile: true } },
          user: { select: { id: true, name: true, email: true } },
          lab: { select: { id: true, status: true } },
        },
        orderBy: { createdAt: "desc" },
        take: limit,
      });

      // Group by recipe
      const byRecipe = reports.reduce(
        (acc, report) => {
          const recipeId = report.recipeId;
          if (!acc[recipeId]) {
            acc[recipeId] = {
              recipe: report.recipe,
              reports: [],
              openCount: 0,
            };
          }
          acc[recipeId].reports.push(report);
          if (report.status === "open" || report.status === "investigating") {
            acc[recipeId].openCount++;
          }
          return acc;
        },
        {} as Record<string, { recipe: typeof reports[0]["recipe"]; reports: typeof reports; openCount: number }>
      );

      return {
        reports,
        byRecipe: Object.values(byRecipe).sort((a, b) => b.openCount - a.openCount),
      };
    }),

  /**
   * Get all reports for a specific recipe (admin only)
   */
  getByRecipe: adminProcedure
    .input(z.object({ recipeId: z.string() }))
    .query(async ({ ctx, input }) => {
      const recipe = await ctx.prisma.recipe.findUnique({
        where: { id: input.recipeId },
      });

      if (!recipe) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Recipe not found",
        });
      }

      const reports = await ctx.prisma.labReport.findMany({
        where: { recipeId: input.recipeId },
        include: {
          user: { select: { id: true, name: true, email: true } },
          lab: { select: { id: true, status: true, createdAt: true } },
        },
        orderBy: { createdAt: "desc" },
      });

      return { recipe, reports };
    }),

  /**
   * Update report status (admin only)
   */
  updateStatus: adminProcedure
    .input(
      z.object({
        id: z.string(),
        status: reportStatusSchema,
        adminNotes: z.string().optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const report = await ctx.prisma.labReport.findUnique({
        where: { id: input.id },
        include: { recipe: true },
      });

      if (!report) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "Report not found",
        });
      }

      const wasOpen = report.status === "open" || report.status === "investigating";
      const isNowFixed = input.status === "fixed";

      // Update the report
      const updated = await ctx.prisma.labReport.update({
        where: { id: input.id },
        data: {
          status: input.status,
          adminNotes: input.adminNotes,
        },
      });

      // If status changed to fixed, notify the user
      if (wasOpen && isNowFixed) {
        await ctx.prisma.notification.create({
          data: {
            userId: report.userId,
            title: "Lab Report Resolved",
            message: `Your report for "${report.recipe.name}" has been fixed. Try deploying a new lab!`,
            type: "success",
            link: "/labs",
          },
        });
      }

      return { success: true, report: updated };
    }),

  /**
   * Bulk resolve reports for a recipe (admin only)
   * Used when fixing a dockerfile to close all related reports
   */
  bulkResolve: adminProcedure
    .input(
      z.object({
        recipeId: z.string(),
        status: z.enum(["fixed", "wont_fix", "duplicate"]),
        adminNotes: z.string().optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      // Get all open reports for this recipe
      const openReports = await ctx.prisma.labReport.findMany({
        where: {
          recipeId: input.recipeId,
          status: { in: ["open", "investigating"] },
        },
        include: { recipe: true },
      });

      if (openReports.length === 0) {
        return { success: true, count: 0 };
      }

      // Update all reports
      await ctx.prisma.labReport.updateMany({
        where: {
          recipeId: input.recipeId,
          status: { in: ["open", "investigating"] },
        },
        data: {
          status: input.status,
          adminNotes: input.adminNotes,
        },
      });

      // Notify all users if status is fixed
      if (input.status === "fixed") {
        const recipeName = openReports[0]?.recipe.name || "Unknown";
        const userIds = [...new Set(openReports.map((r) => r.userId))];

        await ctx.prisma.notification.createMany({
          data: userIds.map((userId) => ({
            userId,
            title: "Lab Report Resolved",
            message: `Your report for "${recipeName}" has been fixed. Try deploying a new lab!`,
            type: "success",
            link: "/labs",
          })),
        });
      }

      return { success: true, count: openReports.length };
    }),

  /**
   * Get report statistics (admin only)
   */
  stats: adminProcedure.query(async ({ ctx }) => {
    const [total, open, investigating, fixed] = await Promise.all([
      ctx.prisma.labReport.count(),
      ctx.prisma.labReport.count({ where: { status: "open" } }),
      ctx.prisma.labReport.count({ where: { status: "investigating" } }),
      ctx.prisma.labReport.count({ where: { status: "fixed" } }),
    ]);

    // Count unique recipes with open reports
    const recipesWithOpenReports = await ctx.prisma.labReport.groupBy({
      by: ["recipeId"],
      where: { status: { in: ["open", "investigating"] } },
    });

    return {
      total,
      open,
      investigating,
      fixed,
      pendingRecipes: recipesWithOpenReports.length,
    };
  }),
});
