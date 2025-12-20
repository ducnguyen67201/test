"use client";

import type { ReactNode } from "react";
import { SessionProvider } from "./session-provider";
import { ThemeProvider } from "./theme-provider";
import { TRPCProvider } from "@/lib/trpc/react";
import { AppLayout } from "@/components/layout/app-layout";
import { FeedbackWidget } from "@/components/feedback/feedback-widget";

interface ProvidersProps {
  children: ReactNode;
}

/**
 * Combined providers wrapper for the application
 * Includes: ThemeProvider, SessionProvider, TRPCProvider, AppLayout
 */
export function Providers({ children }: ProvidersProps) {
  return (
    <ThemeProvider>
      <SessionProvider>
        <TRPCProvider>
          <AppLayout>{children}</AppLayout>
          <FeedbackWidget />
        </TRPCProvider>
      </SessionProvider>
    </ThemeProvider>
  );
}
