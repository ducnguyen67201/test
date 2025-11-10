'use client';

import { useUser } from '@clerk/nextjs';

export interface AuthGuardState {
  isLoaded: boolean;
  isSignedIn: boolean;
  isLoading: boolean;
  shouldRenderGuard: boolean;
}

interface UseAuthGuardOptions {
  redirectTo?: string;
  requireAuth?: boolean;
}

/**
 * Custom hook for handling authentication guards and loading states.
 *
 * @param options - Configuration options
 * @param options.redirectTo - Optional redirect URL (not implemented yet, for future use)
 * @param options.requireAuth - Whether authentication is required (default: true)
 *
 * @returns AuthGuardState object with authentication status
 *
 * @example
 * ```tsx
 * function ProtectedPage() {
 *   const auth = useAuthGuard();
 *
 *   if (auth.isLoading) {
 *     return <LoadingSkeleton />;
 *   }
 *
 *   if (auth.shouldRenderGuard) {
 *     return <AccessDeniedUI />;
 *   }
 *
 *   return <ProtectedContent />;
 * }
 * ```
 */
export function useAuthGuard(options: UseAuthGuardOptions = {}): AuthGuardState {
  const { requireAuth = true } = options;
  const { isLoaded, isSignedIn } = useUser();

  const isLoading = !isLoaded;
  const shouldRenderGuard = requireAuth && isLoaded && !isSignedIn;

  return {
    isLoaded,
    isSignedIn: isSignedIn ?? false,
    isLoading,
    shouldRenderGuard,
  };
}
