/**
 * FastAPI Backend Client
 * Calls the existing Python FastAPI backend
 *
 * ACTUAL ROUTES (no /api prefix):
 *   /auth/login, /auth/register, /auth/me
 *   /recipes
 *   /labs, /labs/{id}
 *   /health
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

interface User {
  id: string;
  email: string;
  created_at: string;
  updated_at: string;
}

interface Recipe {
  id: string;
  name: string;
  description: string | null;
  software: string;
  version_constraint: string | null;
  exploit_family: string | null;
  is_active: boolean;
}

interface Lab {
  id: string;
  recipe_id: string;
  status: 'requested' | 'provisioning' | 'ready' | 'degraded' | 'ending' | 'finished' | 'failed';
  novnc_url: string | null;
  guacamole_url: string | null;
  created_at: string;
  expires_at: string | null;
}

class FastAPIClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('octolab_token', token);
    }
  }

  getToken(): string | null {
    if (this.token) return this.token;
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('octolab_token');
    }
    return this.token;
  }

  clearToken() {
    this.token = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('octolab_token');
    }
  }

  private async fetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    const token = this.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_URL}${endpoint}`, { ...options, headers });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `API Error: ${res.status}`);
    }

    return res.json();
  }

  // Auth - NOTE: paths are /auth/*, NOT /api/auth/*
  async register(email: string, password: string): Promise<LoginResponse> {
    const response = await this.fetch<LoginResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setToken(response.access_token);
    return response;
  }

  async login(email: string, password: string): Promise<LoginResponse> {
    const response = await this.fetch<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setToken(response.access_token);
    return response;
  }

  async getMe(): Promise<User> {
    return this.fetch('/auth/me');
  }

  logout() {
    this.clearToken();
  }

  // Recipes - NOTE: /recipes, NOT /api/recipes
  async getRecipes(): Promise<Recipe[]> {
    return this.fetch('/recipes');
  }

  // Labs - NOTE: /labs, NOT /api/labs
  async createLab(recipeId?: string): Promise<Lab> {
    return this.fetch('/labs', {
      method: 'POST',
      body: JSON.stringify({ recipe_id: recipeId }),
    });
  }

  async getLabs(): Promise<Lab[]> {
    return this.fetch('/labs');
  }

  async getLab(labId: string): Promise<Lab> {
    return this.fetch(`/labs/${labId}`);
  }

  async deleteLab(labId: string): Promise<void> {
    await this.fetch(`/labs/${labId}`, { method: 'DELETE' });
  }

  async connectLab(labId: string): Promise<{ url: string }> {
    return this.fetch(`/labs/${labId}/connect`);
  }

  // Health
  async healthCheck(): Promise<{ status: string }> {
    return this.fetch('/health');
  }
}

export const fastapi = new FastAPIClient();
