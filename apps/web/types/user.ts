/**
 * User profile from the backend API
 */
export interface UserProfile {
  id: string;
  clerk_id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  avatar_url?: string;
  created_at: string;
  updated_at: string;
}

/**
 * Update profile request payload
 */
export interface UpdateProfileRequest {
  first_name?: string;
  last_name?: string;
  avatar_url?: string;
}
