'use client';

import { useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { useApiGet } from '@/lib/api';
import type { UserProfile } from '@/types';

export function TestApiButton() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<string | null>(null);
  const { get, loading, error } = useApiGet<UserProfile>();
  const { getToken } = useAuth();

  const handleGetProfile = async () => {
    setErrorMessage(null);
    setProfile(null);
    setDebugInfo(null);

    try {
      // Get and log the token for debugging
      const token = await getToken();
      const data = await get('/api/me');
      setProfile(data);
    } catch (err) {
      setErrorMessage(error?.message || 'Failed to fetch profile');
    }
  };

  return (
    <div className="card">
      <h2 className="text-xl font-semibold mb-4">Test REST API</h2>

      <div className="space-y-4">
        <div>
          <button
            onClick={handleGetProfile}
            disabled={loading}
            className={`btn-primary ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    fill="none"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Loading...
              </span>
            ) : (
              'Get My Profile (GET /api/me)'
            )}
          </button>
        </div>

        {errorMessage && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-800 font-semibold">Error:</p>
            <p className="text-red-600 text-sm mt-1">{errorMessage}</p>
          </div>
        )}

        {profile && (
          <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-green-800 font-semibold mb-2">Success! Profile Data:</p>
            <pre className="text-sm bg-white p-3 rounded border overflow-auto">
              {JSON.stringify(profile, null, 2)}
            </pre>
          </div>
        )}

        <div className="text-sm text-gray-600 bg-gray-50 p-3 rounded">
          <p className="font-semibold mb-2">API Details:</p>
          <ul className="space-y-1">
            <li>• Endpoint: <code className="bg-white px-1">GET http://localhost:8080/api/me</code></li>
            <li>• Authentication: Clerk JWT token in Authorization header</li>
            <li>• Response: User profile data</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
