import { auth } from '@clerk/nextjs/server';
import { APIError, apiRequest } from './client';

/**
 * Server-side API request helper that automatically gets the token from Clerk
 * Use this in Server Components or Server Actions
 */
export async function serverApiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const session = await auth();
  const token = await session.getToken();

  if (!token) {
    throw new APIError('Unauthorized: No token available', 401);
  }

  return apiRequest<T>(endpoint, options, token);
}
