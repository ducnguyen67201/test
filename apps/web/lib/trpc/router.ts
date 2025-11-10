import { router, publicProcedure, protectedProcedure } from './trpc';
import { z } from 'zod';
import { grpcClient } from '@/lib/grpc/client';
import { TRPCError } from '@trpc/server';
import {
  CreateLabInputSchema,
  ConfirmRequestSchema,
  LabContextSchema,
  LabRequestSchema,
} from '@/lib/schemas/lab-request';

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

  labs: router({
    // Get context (quick picks, guardrails, active lab)
    getContext: protectedProcedure.query(async ({ ctx }) => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/labs/context`, {
          headers: {
            Authorization: `Bearer ${await ctx.session.getToken()}`,
          },
        });

        if (!response.ok) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch lab context',
          });
        }

        const data = await response.json();
        return LabContextSchema.parse(data);
      } catch (error) {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch lab context',
        });
      }
    }),

    // Create draft lab request
    createDraft: protectedProcedure
      .input(CreateLabInputSchema)
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/labs/draft`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${await ctx.session.getToken()}`,
            },
            body: JSON.stringify(input),
          });

          if (!response.ok) {
            const errorData = await response.json();
            throw new TRPCError({
              code: 'BAD_REQUEST',
              message: errorData.error?.message || 'Failed to create draft',
            });
          }

          const data = await response.json();
          return LabRequestSchema.parse(data.lab_request);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to create draft',
          });
        }
      }),

    // Generate blueprint
    generateBlueprint: protectedProcedure
      .input(z.object({ labId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/labs/${input.labId}/blueprint`,
            {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to generate blueprint',
            });
          }

          const data = await response.json();
          return LabRequestSchema.parse(data.lab_request);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to generate blueprint',
          });
        }
      }),

    // Confirm request
    confirmRequest: protectedProcedure
      .input(ConfirmRequestSchema)
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/labs/${input.lab_id}/confirm`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
              body: JSON.stringify({
                justification: input.justification,
              }),
            }
          );

          if (!response.ok) {
            const errorData = await response.json();
            throw new TRPCError({
              code: 'BAD_REQUEST',
              message: errorData.error?.message || 'Failed to confirm request',
              cause: errorData.error?.metadata,
            });
          }

          const data = await response.json();
          return LabRequestSchema.parse(data.lab_request);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to confirm request',
          });
        }
      }),

    // Get active lab
    getActive: protectedProcedure.query(async ({ ctx }) => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/labs/active`, {
          headers: {
            Authorization: `Bearer ${await ctx.session.getToken()}`,
          },
        });

        if (!response.ok) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch active lab',
          });
        }

        const data = await response.json();
        return data.active_lab ? LabRequestSchema.parse(data.active_lab) : null;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch active lab',
        });
      }
    }),

    // Cancel lab
    cancel: protectedProcedure
      .input(z.object({ labId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/labs/${input.labId}/cancel`,
            {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to cancel lab',
            });
          }

          return { success: true };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to cancel lab',
          });
        }
      }),

    // Get lab by ID
    getById: protectedProcedure
      .input(z.object({ labId: z.string().uuid() }))
      .query(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/labs/${input.labId}`,
            {
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'NOT_FOUND',
              message: 'Lab not found',
            });
          }

          const data = await response.json();
          return LabRequestSchema.parse(data.lab_request);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch lab',
          });
        }
      }),
  }),
});

export type AppRouter = typeof appRouter;