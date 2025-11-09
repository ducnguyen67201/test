import { router, publicProcedure, protectedProcedure } from './trpc';
import { z } from 'zod';
import { grpcClient } from '@/lib/grpc/client';
import { TRPCError } from '@trpc/server';

export const appRouter = router({
  health: publicProcedure.query(() => {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
    };
  }),

  user: router({
    me: protectedProcedure.query(async ({ ctx }) => {
      try {
        // Call backend API to get user
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/me`, {
          headers: {
            Authorization: `Bearer ${await ctx.session.getToken()}`,
          },
        });

        if (!response.ok) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch user data',
          });
        }

        const data = await response.json();
        return data;
      } catch (error) {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch user data',
        });
      }
    }),

    syncProfile: protectedProcedure.mutation(async ({ ctx }) => {
      try {
        // Use gRPC client to sync profile
        const token = await ctx.session.getToken();
        if (!token) {
          throw new TRPCError({
            code: 'UNAUTHORIZED',
            message: 'No authentication token',
          });
        }

        const result = await grpcClient.syncUserProfile(token);
        return result;
      } catch (error) {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to sync profile',
        });
      }
    }),

    updateProfile: protectedProcedure
      .input(
        z.object({
          firstName: z.string().optional(),
          lastName: z.string().optional(),
          avatarUrl: z.string().url().optional(),
        })
      )
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/me`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${await ctx.session.getToken()}`,
            },
            body: JSON.stringify({
              first_name: input.firstName,
              last_name: input.lastName,
              avatar_url: input.avatarUrl,
            }),
          });

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to update profile',
            });
          }

          const data = await response.json();
          return data;
        } catch (error) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to update profile',
          });
        }
      }),
  }),
});

export type AppRouter = typeof appRouter;