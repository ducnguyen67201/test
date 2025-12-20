import { z } from "zod";
import { createTRPCRouter, protectedProcedure } from "../init";

const notificationTypeSchema = z.enum(["info", "success", "warning", "error", "message"]);

export const notificationRouter = createTRPCRouter({
  /**
   * Get user's notifications
   */
  list: protectedProcedure
    .input(
      z.object({
        limit: z.number().min(1).max(50).default(20),
        cursor: z.string().optional(),
        unreadOnly: z.boolean().default(false),
      })
    )
    .query(async ({ ctx, input }) => {
      const { limit, cursor, unreadOnly } = input;

      const notifications = await ctx.prisma.notification.findMany({
        where: {
          userId: ctx.session.user.id,
          ...(unreadOnly && { read: false }),
        },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
        orderBy: { createdAt: "desc" },
      });

      let nextCursor: string | undefined;
      if (notifications.length > limit) {
        const nextItem = notifications.pop();
        nextCursor = nextItem?.id;
      }

      return { notifications, nextCursor };
    }),

  /**
   * Get unread count for badge
   */
  unreadCount: protectedProcedure.query(async ({ ctx }) => {
    const count = await ctx.prisma.notification.count({
      where: {
        userId: ctx.session.user.id,
        read: false,
      },
    });

    return { count };
  }),

  /**
   * Mark a notification as read
   */
  markAsRead: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const notification = await ctx.prisma.notification.updateMany({
        where: {
          id: input.id,
          userId: ctx.session.user.id,
        },
        data: { read: true },
      });

      return { success: notification.count > 0 };
    }),

  /**
   * Mark all notifications as read
   */
  markAllAsRead: protectedProcedure.mutation(async ({ ctx }) => {
    await ctx.prisma.notification.updateMany({
      where: {
        userId: ctx.session.user.id,
        read: false,
      },
      data: { read: true },
    });

    return { success: true };
  }),

  /**
   * Delete a notification
   */
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const notification = await ctx.prisma.notification.deleteMany({
        where: {
          id: input.id,
          userId: ctx.session.user.id,
        },
      });

      return { success: notification.count > 0 };
    }),

  /**
   * Clear all notifications
   */
  clearAll: protectedProcedure.mutation(async ({ ctx }) => {
    await ctx.prisma.notification.deleteMany({
      where: {
        userId: ctx.session.user.id,
      },
    });

    return { success: true };
  }),

  /**
   * Create a notification (for internal use / admin)
   */
  create: protectedProcedure
    .input(
      z.object({
        userId: z.string(),
        title: z.string().min(1).max(100),
        message: z.string().min(1).max(500),
        type: notificationTypeSchema.default("info"),
        link: z.string().optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      // Only admins can create notifications for other users
      if (input.userId !== ctx.session.user.id && !ctx.session.user.isSystemAdmin) {
        throw new Error("Unauthorized");
      }

      const notification = await ctx.prisma.notification.create({
        data: {
          userId: input.userId,
          title: input.title,
          message: input.message,
          type: input.type,
          link: input.link,
        },
      });

      return notification;
    }),
});
