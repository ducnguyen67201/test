'use client';

import { ReactNode } from 'react';
import { SignInButton, useUser } from '@clerk/nextjs';
import { useAuthGuard } from '@/hooks/use-auth-guard';
import { AuthenticatedUserContext } from '@/hooks/use-authenticated-user';
import { Button } from '@/components/ui/button';

interface AuthenticatedUserProps {
  children: ReactNode;
  /** Custom loading component */
  loadingComponent?: ReactNode;
  /** Custom access denied component */
  accessDeniedComponent?: ReactNode;
  /** Whether to show sign in button in access denied state */
  showSignInButton?: boolean;
  /** Custom title for access denied state */
  accessDeniedTitle?: string;
  /** Custom message for access denied state */
  accessDeniedMessage?: string;
}

/**
 * Guard component that only renders children when user is authenticated.
 * Shows loading state while checking auth and access denied UI for unauthenticated users.
 *
 * @example
 * ```tsx
 * // Basic usage
 * <AuthenticatedUser>
 *   <ProtectedContent />
 * </AuthenticatedUser>
 *
 * // With custom loading
 * <AuthenticatedUser loadingComponent={<CustomSpinner />}>
 *   <ProtectedContent />
 * </AuthenticatedUser>
 *
 * // With custom access denied
 * <AuthenticatedUser
 *   accessDeniedTitle="Members Only"
 *   accessDeniedMessage="Please sign in to access this feature"
 * >
 *   <ProtectedContent />
 * </AuthenticatedUser>
 * ```
 */
export function AuthenticatedUser({
  children,
  loadingComponent,
  accessDeniedComponent,
  showSignInButton = true,
  accessDeniedTitle = 'Access Denied',
  accessDeniedMessage = 'Please sign in to access this page.',
}: AuthenticatedUserProps) {
  const auth = useAuthGuard();
  const { user } = useUser();

  // Show loading state
  if (auth.isLoading) {
    return (
      loadingComponent ?? (
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
        </div>
      )
    );
  }

  // Show access denied
  if (auth.shouldRenderGuard) {
    return (
      accessDeniedComponent ?? (
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="max-w-md w-full mx-4">
            <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-8 text-center">
              <h2 className="text-2xl font-bold mb-4">{accessDeniedTitle}</h2>
              <p className="text-muted-foreground mb-6">{accessDeniedMessage}</p>
              {showSignInButton && (
                <SignInButton mode="modal">
                  <Button size="lg" className="w-full">
                    Sign In
                  </Button>
                </SignInButton>
              )}
            </div>
          </div>
        </div>
      )
    );
  }

  // Render protected content with user context
  // At this point, we know user is non-null because auth.shouldRenderGuard is false
  return (
    <AuthenticatedUserContext.Provider value={user}>
      {children}
    </AuthenticatedUserContext.Provider>
  );
}
