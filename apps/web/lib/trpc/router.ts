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
import {
  ChatSessionSchema,
  ChatMessagePairSchema,
  ChatSessionWithMessagesSchema,
  CreateChatSessionInputSchema,
  SendMessageInputSchema,
  IntentSchema,
  IntentValidationResultSchema,
} from '@/lib/schemas/chat';
import {
  RecipeSchema,
  CreateRecipeInputSchema,
  CreateRecipeFromIntentInputSchema,
  UpdateRecipeInputSchema,
  RecipeValidationResultSchema,
  RecipeListFiltersSchema,
  RecipeSearchInputSchema,
} from '@/lib/schemas/recipe';

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

  chat: router({
    // Create new chat session
    createSession: protectedProcedure
      .input(CreateChatSessionInputSchema)
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${await ctx.session.getToken()}`,
            },
            body: JSON.stringify(input),
          });

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to create chat session',
            });
          }

          const data = await response.json();
          const session = ChatSessionSchema.parse(data.session);
          return { session };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          console.error('CreateSession error:', error);
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: `Failed to create chat session: ${error instanceof Error ? error.message : 'Unknown error'}`,
          });
        }
      }),

    // Get user sessions
    getSessions: protectedProcedure
      .input(
        z.object({
          limit: z.number().int().min(1).max(100).optional(),
          offset: z.number().int().min(0).optional(),
        })
      )
      .query(async ({ ctx, input }) => {
        try {
          const params = new URLSearchParams();
          if (input.limit) params.append('limit', input.limit.toString());
          if (input.offset) params.append('offset', input.offset.toString());

          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions?${params}`,
            {
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to fetch chat sessions',
            });
          }

          const data = await response.json();
          return {
            sessions: z.array(ChatSessionSchema).parse(data.sessions),
            count: data.count,
          };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch chat sessions',
          });
        }
      }),

    // Get session with messages
    getSessionWithMessages: protectedProcedure
      .input(z.object({ sessionId: z.string().uuid() }))
      .query(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${input.sessionId}/messages`,
            {
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to fetch session messages',
            });
          }

          const data = await response.json();
          return ChatSessionWithMessagesSchema.parse(data);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch session messages',
          });
        }
      }),

    // Send message (non-streaming)
    sendMessage: protectedProcedure
      .input(SendMessageInputSchema)
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${input.session_id}/messages`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
              body: JSON.stringify({ message: input.message }),
            }
          );

          if (!response.ok) {
            const errorText = await response.text();
            console.error('SendMessage backend error:', errorText);
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: `Failed to send message: ${errorText}`,
            });
          }

          const data = await response.json();
          return ChatMessagePairSchema.parse(data);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          console.error('SendMessage error:', error);
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: `Failed to send message: ${error instanceof Error ? error.message : 'Unknown error'}`,
          });
        }
      }),

    // Finalize session and extract intent
    finalizeSession: protectedProcedure
      .input(z.object({ sessionId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${input.sessionId}/finalize`,
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
              message: 'Failed to finalize session',
            });
          }

          const data = await response.json();
          return IntentSchema.parse(data.intent);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to finalize session',
          });
        }
      }),

    // Close session
    closeSession: protectedProcedure
      .input(z.object({ sessionId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${input.sessionId}/close`,
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
              message: 'Failed to close session',
            });
          }

          return { success: true };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to close session',
          });
        }
      }),

    // Delete session
    deleteSession: protectedProcedure
      .input(z.object({ sessionId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${input.sessionId}`,
            {
              method: 'DELETE',
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to delete session',
            });
          }

          return { success: true };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to delete session',
          });
        }
      }),
  }),

  recipe: router({
    // Create recipe manually
    createManual: protectedProcedure
      .input(CreateRecipeInputSchema)
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/recipes`, {
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
              message: errorData.error?.message || 'Failed to create recipe',
            });
          }

          const data = await response.json();
          return RecipeSchema.parse(data.recipe);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to create recipe',
          });
        }
      }),

    // Create recipe from intent
    createFromIntent: protectedProcedure
      .input(CreateRecipeFromIntentInputSchema)
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/from-intent`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
              body: JSON.stringify(input),
            }
          );

          if (!response.ok) {
            const errorData = await response.json();
            throw new TRPCError({
              code: 'BAD_REQUEST',
              message: errorData.error?.message || 'Failed to create recipe from intent',
            });
          }

          const data = await response.json();
          return RecipeSchema.parse(data.recipe);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to create recipe from intent',
          });
        }
      }),

    // List recipes
    list: protectedProcedure.input(RecipeListFiltersSchema).query(async ({ ctx, input }) => {
      try {
        const params = new URLSearchParams();
        if (input.software) params.append('software', input.software);
        if (input.limit) params.append('limit', input.limit.toString());
        if (input.offset) params.append('offset', input.offset.toString());

        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/recipes?${params}`,
          {
            headers: {
              Authorization: `Bearer ${await ctx.session.getToken()}`,
            },
          }
        );

        if (!response.ok) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch recipes',
          });
        }

        const data = await response.json();
        return {
          recipes: z.array(RecipeSchema).parse(data.recipes),
          count: data.count,
        };
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch recipes',
        });
      }
    }),

    // Search recipes
    search: protectedProcedure.input(RecipeSearchInputSchema).query(async ({ ctx, input }) => {
      try {
        const params = new URLSearchParams({ q: input.query });
        if (input.limit) params.append('limit', input.limit.toString());
        if (input.offset) params.append('offset', input.offset.toString());

        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/search?${params}`,
          {
            headers: {
              Authorization: `Bearer ${await ctx.session.getToken()}`,
            },
          }
        );

        if (!response.ok) {
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to search recipes',
          });
        }

        const data = await response.json();
        return {
          recipes: z.array(RecipeSchema).parse(data.recipes),
          count: data.count,
        };
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to search recipes',
        });
      }
    }),

    // Get recipe by ID
    getById: protectedProcedure
      .input(z.object({ recipeId: z.string().uuid() }))
      .query(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/${input.recipeId}`,
            {
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'NOT_FOUND',
              message: 'Recipe not found',
            });
          }

          const data = await response.json();
          return RecipeSchema.parse(data.recipe);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch recipe',
          });
        }
      }),

    // Update recipe
    update: protectedProcedure
      .input(
        z.object({
          recipeId: z.string().uuid(),
          data: UpdateRecipeInputSchema,
        })
      )
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/${input.recipeId}`,
            {
              method: 'PUT',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
              body: JSON.stringify(input.data),
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to update recipe',
            });
          }

          const data = await response.json();
          return RecipeSchema.parse(data.recipe);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to update recipe',
          });
        }
      }),

    // Delete recipe
    delete: protectedProcedure
      .input(z.object({ recipeId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/${input.recipeId}`,
            {
              method: 'DELETE',
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to delete recipe',
            });
          }

          return { success: true };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to delete recipe',
          });
        }
      }),

    // Activate recipe
    activate: protectedProcedure
      .input(z.object({ recipeId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/${input.recipeId}/activate`,
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
              message: 'Failed to activate recipe',
            });
          }

          return { success: true };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to activate recipe',
          });
        }
      }),

    // Deactivate recipe
    deactivate: protectedProcedure
      .input(z.object({ recipeId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/${input.recipeId}/deactivate`,
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
              message: 'Failed to deactivate recipe',
            });
          }

          return { success: true };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to deactivate recipe',
          });
        }
      }),

    // Validate recipe
    validate: protectedProcedure
      .input(z.object({ recipeId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/recipes/${input.recipeId}/validate`,
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
              message: 'Failed to validate recipe',
            });
          }

          const data = await response.json();
          return RecipeValidationResultSchema.parse(data.validation_result);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to validate recipe',
          });
        }
      }),
  }),

  intent: router({
    // Get pending intents
    getPending: protectedProcedure
      .input(
        z.object({
          limit: z.number().int().min(1).max(100).optional(),
          offset: z.number().int().min(0).optional(),
        })
      )
      .query(async ({ ctx, input }) => {
        try {
          const params = new URLSearchParams();
          if (input.limit) params.append('limit', input.limit.toString());
          if (input.offset) params.append('offset', input.offset.toString());

          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/intents/pending?${params}`,
            {
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to fetch pending intents',
            });
          }

          const data = await response.json();
          return {
            intents: z.array(IntentSchema).parse(data.intents),
            count: data.count,
          };
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch pending intents',
          });
        }
      }),

    // Get intent by ID
    getById: protectedProcedure
      .input(z.object({ intentId: z.string().uuid() }))
      .query(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/intents/${input.intentId}`,
            {
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'NOT_FOUND',
              message: 'Intent not found',
            });
          }

          const data = await response.json();
          return IntentSchema.parse(data.intent);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch intent',
          });
        }
      }),

    // Approve intent
    approve: protectedProcedure
      .input(z.object({ intentId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/intents/${input.intentId}/approve`,
            {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
            }
          );

          if (!response.ok) {
            const errorData = await response.json();
            throw new TRPCError({
              code: 'BAD_REQUEST',
              message: errorData.error?.message || 'Failed to approve intent',
            });
          }

          const data = await response.json();
          return IntentSchema.parse(data.intent);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to approve intent',
          });
        }
      }),

    // Reject intent
    reject: protectedProcedure
      .input(
        z.object({
          intentId: z.string().uuid(),
          reason: z.string().min(1, 'Rejection reason is required'),
        })
      )
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/intents/${input.intentId}/reject`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${await ctx.session.getToken()}`,
              },
              body: JSON.stringify({ reason: input.reason }),
            }
          );

          if (!response.ok) {
            throw new TRPCError({
              code: 'INTERNAL_SERVER_ERROR',
              message: 'Failed to reject intent',
            });
          }

          const data = await response.json();
          return IntentSchema.parse(data.intent);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to reject intent',
          });
        }
      }),

    // Validate intent
    validate: protectedProcedure
      .input(z.object({ intentId: z.string().uuid() }))
      .mutation(async ({ ctx, input }) => {
        try {
          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/api/intents/${input.intentId}/validate`,
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
              message: 'Failed to validate intent',
            });
          }

          const data = await response.json();
          return IntentValidationResultSchema.parse(data.validation_result);
        } catch (error) {
          if (error instanceof TRPCError) throw error;
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to validate intent',
          });
        }
      }),
  }),
});

export type AppRouter = typeof appRouter;