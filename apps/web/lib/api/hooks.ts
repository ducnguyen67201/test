'use client';

import { useAuth } from '@clerk/nextjs';
import { useState, useCallback } from 'react';
import { clientApiRequest, APIError } from './client';

/**
 * Hook for making authenticated API requests from client components
 */
export function useApi() {
  const { getToken } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<APIError | null>(null);

  const request = useCallback(
    async <T = any>(endpoint: string, options: RequestInit = {}): Promise<T> => {
      setLoading(true);
      setError(null);

      try {
        const token = await getToken();
        if (!token) {
          throw new APIError('Not authenticated', 401);
        }

        const data = await clientApiRequest<T>(endpoint, token, options);
        return data;
      } catch (err) {
        const apiError = err instanceof APIError ? err : new APIError('Unknown error', 0);
        setError(apiError);
        throw apiError;
      } finally {
        setLoading(false);
      }
    },
    [getToken]
  );

  return {
    request,
    loading,
    error,
  };
}

/**
 * Hook for GET requests
 */
export function useApiGet<T = any>() {
  const { request, loading, error } = useApi();

  const get = useCallback(
    async (endpoint: string): Promise<T> => {
      return request<T>(endpoint, { method: 'GET' });
    },
    [request]
  );

  return { get, loading, error };
}

/**
 * Hook for POST requests
 */
export function useApiPost<T = any, B = any>() {
  const { request, loading, error } = useApi();

  const post = useCallback(
    async (endpoint: string, body: B): Promise<T> => {
      return request<T>(endpoint, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },
    [request]
  );

  return { post, loading, error };
}

/**
 * Hook for PATCH requests
 */
export function useApiPatch<T = any, B = any>() {
  const { request, loading, error } = useApi();

  const patch = useCallback(
    async (endpoint: string, body: B): Promise<T> => {
      return request<T>(endpoint, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
    },
    [request]
  );

  return { patch, loading, error };
}

/**
 * Hook for DELETE requests
 */
export function useApiDelete<T = any>() {
  const { request, loading, error } = useApi();

  const del = useCallback(
    async (endpoint: string): Promise<T> => {
      return request<T>(endpoint, { method: 'DELETE' });
    },
    [request]
  );

  return { delete: del, loading, error };
}
