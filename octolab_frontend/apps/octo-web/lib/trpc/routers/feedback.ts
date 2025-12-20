import { z } from "zod";
import { Prisma } from "@prisma/client";
import { createTRPCRouter, publicProcedure, protectedProcedure } from "../init";

const feedbackTypeSchema = z.enum(["bug", "feature", "improvement", "other"]);

// Use a more specific schema for metadata that matches Prisma's JSON type
const metadataSchema = z
  .object({
    userAgent: z.string().optional(),
    screenWidth: z.number().optional(),
    screenHeight: z.number().optional(),
  })
  .optional();

const createFeedbackSchema = z.object({
  type: feedbackTypeSchema,
  message: z.string().min(10, "Feedback must be at least 10 characters").max(2000),
  rating: z.number().min(1).max(5).optional(),
  page: z.string().optional(),
  metadata: metadataSchema,
});

export const feedbackRouter = createTRPCRouter({
  /**
   * Submit feedback (works for both authenticated and anonymous users)
   */
  submit: publicProcedure
    .input(createFeedbackSchema)
    .mutation(async ({ ctx, input }) => {
      const feedback = await ctx.prisma.feedback.create({
        data: {
          userId: ctx.session?.user?.id ?? null,
          type: input.type,
          message: input.message,
          rating: input.rating,
          page: input.page,
          metadata: input.metadata as Prisma.InputJsonValue | undefined,
          status: "new",
        },
      });

      return {
        success: true,
        id: feedback.id,
        message: "Thank you for your feedback!",
      };
    }),

  /**
   * List all feedback (admin only)
   */
  list: protectedProcedure
    .input(
      z.object({
        status: z.enum(["new", "reviewed", "resolved", "archived"]).optional(),
        type: feedbackTypeSchema.optional(),
        limit: z.number().min(1).max(100).default(50),
        cursor: z.string().optional(),
      })
    )
    .query(async ({ ctx, input }) => {
      // Check if user is admin
      if (!ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      const { status, type, limit, cursor } = input;

      const feedbacks = await ctx.prisma.feedback.findMany({
        where: {
          ...(status && { status }),
          ...(type && { type }),
        },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
        orderBy: { createdAt: "desc" },
      });

      let nextCursor: string | undefined;
      if (feedbacks.length > limit) {
        const nextItem = feedbacks.pop();
        nextCursor = nextItem?.id;
      }

      return { feedbacks, nextCursor };
    }),

  /**
   * Update feedback status (admin only)
   */
  updateStatus: protectedProcedure
    .input(
      z.object({
        id: z.string(),
        status: z.enum(["new", "reviewed", "resolved", "archived"]),
      })
    )
    .mutation(async ({ ctx, input }) => {
      if (!ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      const feedback = await ctx.prisma.feedback.update({
        where: { id: input.id },
        data: { status: input.status },
      });

      return feedback;
    }),

  /**
   * Get feedback stats (admin only)
   */
  stats: protectedProcedure.query(async ({ ctx }) => {
    if (!ctx.session.user.isSystemAdmin) {
      throw new Error("Unauthorized");
    }

    const [total, newCount, bugCount, featureCount, improvementCount] = await Promise.all([
      ctx.prisma.feedback.count(),
      ctx.prisma.feedback.count({ where: { status: "new" } }),
      ctx.prisma.feedback.count({ where: { type: "bug" } }),
      ctx.prisma.feedback.count({ where: { type: "feature" } }),
      ctx.prisma.feedback.count({ where: { type: "improvement" } }),
    ]);

    return {
      total,
      new: newCount,
      bugs: bugCount,
      features: featureCount,
      improvements: improvementCount,
    };
  }),

  /**
   * Get single feedback by ID (admin only)
   */
  getById: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ ctx, input }) => {
      if (!ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      const feedback = await ctx.prisma.feedback.findUnique({
        where: { id: input.id },
      });

      return feedback;
    }),

  /**
   * Delete feedback (admin only)
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      if (!ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      await ctx.prisma.feedback.delete({
        where: { id: input.id },
      });

      return { success: true };
    }),

  /**
   * Bulk delete feedback (admin only)
   */
  bulkDelete: protectedProcedure
    .input(z.object({ ids: z.array(z.string()) }))
    .mutation(async ({ ctx, input }) => {
      if (!ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      const result = await ctx.prisma.feedback.deleteMany({
        where: { id: { in: input.ids } },
      });

      return { success: true, count: result.count };
    }),

  /**
   * Bulk update status (admin only)
   */
  bulkUpdateStatus: protectedProcedure
    .input(
      z.object({
        ids: z.array(z.string()),
        status: z.enum(["new", "reviewed", "resolved", "archived"]),
      })
    )
    .mutation(async ({ ctx, input }) => {
      if (!ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      const result = await ctx.prisma.feedback.updateMany({
        where: { id: { in: input.ids } },
        data: { status: input.status },
      });

      return { success: true, count: result.count };
    }),

  /**
   * Get current user's feedback history
   */
  myFeedback: protectedProcedure
    .input(
      z.object({
        limit: z.number().min(1).max(50).default(20),
        cursor: z.string().optional(),
      }).optional()
    )
    .query(async ({ ctx, input }) => {
      const limit = input?.limit ?? 20;
      const cursor = input?.cursor;

      const feedbacks = await ctx.prisma.feedback.findMany({
        where: { userId: ctx.session.user.id },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
        orderBy: { createdAt: "desc" },
      });

      let nextCursor: string | undefined;
      if (feedbacks.length > limit) {
        const nextItem = feedbacks.pop();
        nextCursor = nextItem?.id;
      }

      return { feedbacks, nextCursor };
    }),
});
