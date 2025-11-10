'use client';

import { createContext, useContext } from 'react';
import type { UserResource } from '@clerk/types';

/**
 * Context that provides a guaranteed authenticated user.
 * This context is only available inside the <AuthenticatedUser> component.
 */
export const AuthenticatedUserContext = createContext<UserResource | null>(null);

/**
 * Hook to access the authenticated user within an <AuthenticatedUser> guard.
 * This hook returns a guaranteed non-null user object.
 *
 * @throws Error if used outside of <AuthenticatedUser> component
 *
 * @example
 * ```tsx
 * function ProfilePage() {
 *   const user = useAuthenticatedUser();
 *   // user is guaranteed to be non-null here
 *   return <div>Welcome, {user.firstName}!</div>;
 * }
 *
 * export default function Page() {
 *   return (
 *     <AuthenticatedUser>
 *       <ProfilePage />
 *     </AuthenticatedUser>
 *   );
 * }
 * ```
 */
export function useAuthenticatedUser(): UserResource {
  const user = useContext(AuthenticatedUserContext);

  if (!user) {
    throw new Error(
      'useAuthenticatedUser must be used within an <AuthenticatedUser> component. ' +
      'Make sure your component is wrapped with <AuthenticatedUser>.</AuthenticatedUser>'
    );
  }

  return user;
}
