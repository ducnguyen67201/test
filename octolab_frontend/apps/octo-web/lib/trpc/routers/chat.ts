import { z } from "zod";
import { Prisma } from "@prisma/client";
import { createTRPCRouter, protectedProcedure } from "../init";

export const chatRouter = createTRPCRouter({
  /**
   * Create a new chat session
   */
  createSession: protectedProcedure
    .input(z.object({ title: z.string().optional() }).optional())
    .mutation(async ({ ctx, input }) => {
      const session = await ctx.prisma.chatSession.create({
        data: {
          userId: ctx.session.user.id,
          title: input?.title ?? "New Chat",
        },
      });

      return {
        id: session.id,
        title: session.title,
        createdAt: session.createdAt.toISOString(),
      };
    }),

  /**
   * List user's chat sessions
   */
  listSessions: protectedProcedure
    .input(
      z.object({
        limit: z.number().min(1).max(50).default(20),
        cursor: z.string().optional(),
      }).optional()
    )
    .query(async ({ ctx, input }) => {
      const limit = input?.limit ?? 20;
      const cursor = input?.cursor;

      const sessions = await ctx.prisma.chatSession.findMany({
        where: { userId: ctx.session.user.id },
        orderBy: { updatedAt: "desc" },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
        include: {
          messages: {
            take: 1,
            orderBy: { createdAt: "asc" },
            where: { role: "user" },
          },
        },
      });

      let nextCursor: string | undefined;
      if (sessions.length > limit) {
        const nextItem = sessions.pop();
        nextCursor = nextItem?.id;
      }

      return {
        sessions: sessions.map((s) => ({
          id: s.id,
          title: s.title,
          preview: s.messages[0]?.content.slice(0, 100) ?? null,
          createdAt: s.createdAt.toISOString(),
          updatedAt: s.updatedAt.toISOString(),
        })),
        nextCursor,
      };
    }),

  /**
   * Get a chat session with all messages
   */
  getSession: protectedProcedure
    .input(z.object({ sessionId: z.string() }))
    .query(async ({ ctx, input }) => {
      const session = await ctx.prisma.chatSession.findFirst({
        where: {
          id: input.sessionId,
          userId: ctx.session.user.id,
        },
        include: {
          messages: {
            orderBy: { createdAt: "asc" },
          },
        },
      });

      if (!session) {
        return null;
      }

      return {
        id: session.id,
        title: session.title,
        createdAt: session.createdAt.toISOString(),
        updatedAt: session.updatedAt.toISOString(),
        messages: session.messages.map((m) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          metadata: m.metadata as Record<string, unknown> | null,
          createdAt: m.createdAt.toISOString(),
        })),
      };
    }),

  /**
   * Add a message to a chat session
   */
  addMessage: protectedProcedure
    .input(
      z.object({
        sessionId: z.string(),
        role: z.enum(["user", "assistant"]),
        content: z.string(),
        metadata: z.record(z.unknown()).optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      // Verify session ownership
      const session = await ctx.prisma.chatSession.findFirst({
        where: {
          id: input.sessionId,
          userId: ctx.session.user.id,
        },
      });

      if (!session) {
        throw new Error("Chat session not found");
      }

      const message = await ctx.prisma.chatMessage.create({
        data: {
          sessionId: input.sessionId,
          role: input.role,
          content: input.content,
          metadata: (input.metadata ?? undefined) as Prisma.InputJsonValue | undefined,
        },
      });

      // Update session's updatedAt
      await ctx.prisma.chatSession.update({
        where: { id: input.sessionId },
        data: { updatedAt: new Date() },
      });

      return {
        id: message.id,
        role: message.role,
        content: message.content,
        metadata: message.metadata as Record<string, unknown> | null,
        createdAt: message.createdAt.toISOString(),
      };
    }),

  /**
   * Update session title
   */
  updateTitle: protectedProcedure
    .input(
      z.object({
        sessionId: z.string(),
        title: z.string().min(1).max(200),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const session = await ctx.prisma.chatSession.updateMany({
        where: {
          id: input.sessionId,
          userId: ctx.session.user.id,
        },
        data: { title: input.title },
      });

      if (session.count === 0) {
        throw new Error("Chat session not found");
      }

      return { success: true };
    }),

  /**
   * Delete a chat session
   */
  deleteSession: protectedProcedure
    .input(z.object({ sessionId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const result = await ctx.prisma.chatSession.deleteMany({
        where: {
          id: input.sessionId,
          userId: ctx.session.user.id,
        },
      });

      if (result.count === 0) {
        throw new Error("Chat session not found");
      }

      return { success: true };
    }),

  /**
   * Auto-generate title from first message
   */
  generateTitle: protectedProcedure
    .input(z.object({ sessionId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const session = await ctx.prisma.chatSession.findFirst({
        where: {
          id: input.sessionId,
          userId: ctx.session.user.id,
        },
        include: {
          messages: {
            where: { role: "user" },
            take: 1,
            orderBy: { createdAt: "asc" },
          },
        },
      });

      if (!session) {
        throw new Error("Chat session not found");
      }

      // Generate title from first user message
      const firstMessage = session.messages[0]?.content ?? "";
      let title = firstMessage.slice(0, 50);
      if (firstMessage.length > 50) {
        title += "...";
      }
      title = title || "New Chat";

      await ctx.prisma.chatSession.update({
        where: { id: input.sessionId },
        data: { title },
      });

      return { title };
    }),

  /**
   * Clear all chat history for current user
   */
  clearAllHistory: protectedProcedure.mutation(async ({ ctx }) => {
    const result = await ctx.prisma.chatSession.deleteMany({
      where: { userId: ctx.session.user.id },
    });

    return { success: true, count: result.count };
  }),

  /**
   * Get chat statistics for current user
   */
  stats: protectedProcedure.query(async ({ ctx }) => {
    const [totalSessions, totalMessages] = await Promise.all([
      ctx.prisma.chatSession.count({
        where: { userId: ctx.session.user.id },
      }),
      ctx.prisma.chatMessage.count({
        where: {
          session: { userId: ctx.session.user.id },
        },
      }),
    ]);

    return {
      totalSessions,
      totalMessages,
    };
  }),

  /**
   * Duplicate a chat session
   */
  duplicateSession: protectedProcedure
    .input(z.object({ sessionId: z.string() }))
    .mutation(async ({ ctx, input }) => {
      const originalSession = await ctx.prisma.chatSession.findFirst({
        where: {
          id: input.sessionId,
          userId: ctx.session.user.id,
        },
        include: { messages: true },
      });

      if (!originalSession) {
        throw new Error("Chat session not found");
      }

      // Create new session with copied messages
      const newSession = await ctx.prisma.chatSession.create({
        data: {
          userId: ctx.session.user.id,
          title: `${originalSession.title} (copy)`,
          messages: {
            create: originalSession.messages.map((m) => ({
              role: m.role,
              content: m.content,
              metadata: m.metadata ?? undefined,
            })),
          },
        },
        include: { messages: true },
      });

      return {
        id: newSession.id,
        title: newSession.title,
        messageCount: newSession.messages.length,
      };
    }),

  /**
   * Search messages across all sessions
   */
  searchMessages: protectedProcedure
    .input(
      z.object({
        query: z.string().min(2),
        limit: z.number().min(1).max(50).default(20),
      })
    )
    .query(async ({ ctx, input }) => {
      const messages = await ctx.prisma.chatMessage.findMany({
        where: {
          session: { userId: ctx.session.user.id },
          content: { contains: input.query, mode: "insensitive" },
        },
        include: {
          session: {
            select: { id: true, title: true },
          },
        },
        take: input.limit,
        orderBy: { createdAt: "desc" },
      });

      return messages.map((m) => ({
        id: m.id,
        content: m.content.slice(0, 200),
        role: m.role,
        sessionId: m.session.id,
        sessionTitle: m.session.title,
        createdAt: m.createdAt.toISOString(),
      }));
    }),
});
