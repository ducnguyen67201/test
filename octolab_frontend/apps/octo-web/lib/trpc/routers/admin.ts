import { z } from "zod";
import { createTRPCRouter, adminProcedure } from "../init";

// Review queue item schema
const reviewItemSchema = z.object({
  id: z.string(),
  cve_id: z.string(),
  recipe_name: z.string(),
  last_dockerfile: z.string().nullable(),
  errors: z.array(z.string()),
  attempts: z.number(),
  status: z.string(),
  confidence_score: z.number().nullable(),
  confidence_reason: z.string().nullable(),
  created_at: z.string().nullable(),
});

export const adminRouter = createTRPCRouter({
  listUsers: adminProcedure
    .input(
      z.object({
        search: z.string().optional(),
        limit: z.number().min(1).max(100).default(50),
        cursor: z.string().optional(),
      })
    )
    .query(async ({ ctx, input }) => {
      const { search, limit, cursor } = input;

      const users = await ctx.prisma.user.findMany({
        where: search
          ? {
              OR: [
                { name: { contains: search, mode: "insensitive" } },
                { email: { contains: search, mode: "insensitive" } },
              ],
            }
          : undefined,
        select: {
          id: true,
          name: true,
          email: true,
          image: true,
          isSystemAdmin: true,
          isRestricted: true,
          createdAt: true,
          emailVerified: true,
        },
        take: limit + 1,
        cursor: cursor ? { id: cursor } : undefined,
        orderBy: { createdAt: "desc" },
      });

      let nextCursor: string | undefined;
      if (users.length > limit) {
        const nextItem = users.pop();
        nextCursor = nextItem?.id;
      }

      return { users, nextCursor };
    }),

  getStats: adminProcedure.query(async ({ ctx }) => {
    const [totalUsers, adminCount, restrictedCount] = await Promise.all([
      ctx.prisma.user.count(),
      ctx.prisma.user.count({ where: { isSystemAdmin: true } }),
      ctx.prisma.user.count({ where: { isRestricted: true } }),
    ]);

    return {
      totalUsers,
      adminCount,
      restrictedCount,
    };
  }),

  toggleSystemAdmin: adminProcedure
    .input(
      z.object({
        userId: z.string(),
        isSystemAdmin: z.boolean(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const { userId, isSystemAdmin } = input;

      // Prevent removing your own admin status
      if (ctx.session.user.id === userId && !isSystemAdmin) {
        throw new Error("Cannot remove your own admin status");
      }

      const user = await ctx.prisma.user.update({
        where: { id: userId },
        data: { isSystemAdmin },
        select: {
          id: true,
          email: true,
          isSystemAdmin: true,
        },
      });

      return user;
    }),

  restrictUser: adminProcedure
    .input(
      z.object({
        userId: z.string(),
        isRestricted: z.boolean(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const { userId, isRestricted } = input;

      // Prevent restricting yourself
      if (ctx.session.user.id === userId) {
        throw new Error("Cannot restrict yourself");
      }

      const user = await ctx.prisma.user.update({
        where: { id: userId },
        data: { isRestricted },
        select: {
          id: true,
          email: true,
          isRestricted: true,
        },
      });

      return user;
    }),

  getUserById: adminProcedure
    .input(z.object({ userId: z.string() }))
    .query(async ({ ctx, input }) => {
      const user = await ctx.prisma.user.findUnique({
        where: { id: input.userId },
        select: {
          id: true,
          name: true,
          email: true,
          image: true,
          isSystemAdmin: true,
          isRestricted: true,
          createdAt: true,
          updatedAt: true,
          emailVerified: true,
          _count: {
            select: {
              labs: true,
            },
          },
        },
      });

      return user;
    }),

  // ========== Dockerfile Review Queue ==========

  listReviewQueue: adminProcedure
    .input(
      z.object({
        status: z.string().optional(),
        limit: z.number().min(1).max(100).default(50),
      })
    )
    .query(async ({ ctx, input }) => {
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";
      const url = new URL("/dockerfile-review-queue/", octoLabBaseUrl);
      if (input.status) url.searchParams.set("status", input.status);
      url.searchParams.set("limit", String(input.limit));

      const response = await fetch(url.toString(), {
        headers: {
          ...(process.env.OCTOLAB_SERVICE_TOKEN && {
            "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
          }),
          "X-User-Email": ctx.session.user.email ?? "admin@system",
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch review queue: ${response.status}`);
      }

      const data = await response.json();
      return z.array(reviewItemSchema).parse(data);
    }),

  getReviewItem: adminProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ ctx, input }) => {
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";

      const response = await fetch(`${octoLabBaseUrl}/dockerfile-review-queue/${input.id}`, {
        headers: {
          ...(process.env.OCTOLAB_SERVICE_TOKEN && {
            "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
          }),
          "X-User-Email": ctx.session.user.email ?? "admin@system",
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch review item: ${response.status}`);
      }

      return reviewItemSchema.parse(await response.json());
    }),

  approveReview: adminProcedure
    .input(
      z.object({
        id: z.string(),
        fixedDockerfile: z.string(),
        fixedSourceFiles: z.array(z.object({ filename: z.string(), content: z.string() })).default([]),
        baseImage: z.string().optional(),
        exposedPorts: z.array(z.number()).default([]),
        exploitHint: z.string().optional(),
        aliases: z.array(z.string()).default([]),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";

      const response = await fetch(`${octoLabBaseUrl}/dockerfile-review-queue/${input.id}/approve`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(process.env.OCTOLAB_SERVICE_TOKEN && {
            "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
          }),
          "X-User-Email": ctx.session.user.email ?? "admin@system",
        },
        body: JSON.stringify({
          fixed_dockerfile: input.fixedDockerfile,
          fixed_source_files: input.fixedSourceFiles,
          base_image: input.baseImage,
          exposed_ports: input.exposedPorts,
          exploit_hint: input.exploitHint,
          aliases: input.aliases,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Approve failed" }));
        throw new Error(error.detail || "Failed to approve");
      }

      return response.json();
    }),

  rejectReview: adminProcedure
    .input(
      z.object({
        id: z.string(),
        reason: z.string().default("Invalid or unsupported CVE"),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";

      const response = await fetch(`${octoLabBaseUrl}/dockerfile-review-queue/${input.id}/reject`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(process.env.OCTOLAB_SERVICE_TOKEN && {
            "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
          }),
          "X-User-Email": ctx.session.user.email ?? "admin@system",
        },
        body: JSON.stringify({ reason: input.reason }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Reject failed" }));
        throw new Error(error.detail || "Failed to reject");
      }

      return response.json();
    }),

  testBuild: adminProcedure
    .input(
      z.object({
        dockerfile: z.string(),
        sourceFiles: z.array(z.object({ filename: z.string(), content: z.string() })).default([]),
      })
    )
    .mutation(async ({ ctx, input }) => {
      const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://127.0.0.1:8000";

      const response = await fetch(`${octoLabBaseUrl}/dockerfile-review-queue/test-build`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(process.env.OCTOLAB_SERVICE_TOKEN && {
            "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
          }),
          "X-User-Email": ctx.session.user.email ?? "admin@system",
        },
        body: JSON.stringify({
          dockerfile: input.dockerfile,
          source_files: input.sourceFiles,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Test build failed" }));
        throw new Error(error.detail || "Failed to run test build");
      }

      const result = await response.json();
      return {
        success: result.success as boolean,
        error: result.error as string | undefined,
        logs: result.logs as string | undefined,
        duration_seconds: result.duration_seconds as number | undefined,
      };
    }),
});
