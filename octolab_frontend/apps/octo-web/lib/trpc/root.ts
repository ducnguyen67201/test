import { createCallerFactory, createTRPCRouter } from "./init";
import { authRouter } from "./routers/auth";
import { userRouter } from "./routers/user";
import { recipeRouter } from "./routers/recipe";
import { adminRouter } from "./routers/admin";
import { feedbackRouter } from "./routers/feedback";
import { chatRouter } from "./routers/chat";
import { notificationRouter } from "./routers/notification";
import { labRouter } from "./routers/lab";
import { labReportRouter } from "./routers/labReport";

/**
 * Root router that combines all sub-routers
 * Add new routers here as the application grows
 */
export const appRouter = createTRPCRouter({
  auth: authRouter,
  user: userRouter,
  recipe: recipeRouter,
  admin: adminRouter,
  feedback: feedbackRouter,
  chat: chatRouter,
  notification: notificationRouter,
  lab: labRouter,
  labReport: labReportRouter,
});

/**
 * Export type definition of the API for client-side type inference
 * This is the key to unified types between server and client
 */
export type AppRouter = typeof appRouter;

/**
 * Create a server-side caller for direct procedure calls
 * Useful for Server Components and API routes
 */
export const createCaller = createCallerFactory(appRouter);
