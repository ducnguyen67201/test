/**
 * Generic API response wrapper
 */
export interface APIResponse<T> {
  data: T;
  message?: string;
}

/**
 * API error response
 */
export interface APIErrorResponse {
  error: string;
  message: string;
  status: number;
}
