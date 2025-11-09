import { auth } from '@clerk/nextjs/server';

/**
 * API Client configuration
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

/**
 * Custom error class for API errors
 */
export class APIError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: any
  ) {
    super(message);
    this.name = 'APIError';
  }
}

/**
 * Makes an authenticated API request to the backend
 * Automatically includes Clerk JWT token in the Authorization header
 *
 * @param endpoint - API endpoint (e.g., '/api/me')
 * @param options - Fetch options (method, body, etc.)
 * @param token - Optional token (if not provided, will be retrieved from Clerk)
 * @returns Promise with the response data
 */
export async function apiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {},
  token?: string
): Promise<T> {
  // Get token from Clerk if not provided
  let authToken = token;
  if (!authToken && typeof window !== 'undefined') {
    // Client-side: token should be passed in
    throw new Error('Token is required for client-side API requests');
  }

  const url = `${API_BASE_URL}${endpoint}`;

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  // Add authorization header if token is provided
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Handle non-2xx responses
    if (!response.ok) {
      let errorData;
      try {
        errorData = await response.json();
      } catch {
        errorData = { message: response.statusText };
      }

      throw new APIError(
        errorData.message || `API request failed: ${response.status}`,
        response.status,
        errorData
      );
    }

    // Parse JSON response
    const data = await response.json();
    return data as T;
  } catch (error) {
    if (error instanceof APIError) {
      throw error;
    }

    // Network or other errors
    throw new APIError(
      error instanceof Error ? error.message : 'Unknown error occurred',
      0
    );
  }
}

/**
 * Server-side API request helper that automatically gets the token from Clerk
 * Use this in Server Components or Server Actions
 */
export async function serverApiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const { getToken } = auth();
  const token = await getToken();

  if (!token) {
    throw new APIError('Unauthorized: No token available', 401);
  }

  return apiRequest<T>(endpoint, options, token);
}

/**
 * Client-side API request helper
 * Requires token to be passed explicitly (get it from useAuth hook)
 */
export async function clientApiRequest<T = any>(
  endpoint: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  if (!token) {
    throw new APIError('Unauthorized: No token provided', 401);
  }

  return apiRequest<T>(endpoint, options, token);
}
