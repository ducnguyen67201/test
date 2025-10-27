'use client';

import { useState } from 'react';
import { useUser } from '@clerk/nextjs';
import { trpc } from '@/lib/trpc/provider';

export function ProfileSync() {
  const { user } = useUser();
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const utils = trpc.useUtils();
  const syncMutation = trpc.user.syncProfile.useMutation({
    onMutate: () => {
      setStatus('loading');
      setMessage('Syncing profile...');
    },
    onSuccess: (data) => {
      setStatus('success');
      setMessage(data.created ? 'Profile created successfully!' : 'Profile updated successfully!');
      utils.user.me.invalidate();
    },
    onError: (error) => {
      setStatus('error');
      setMessage(`Error: ${error.message}`);
    },
  });

  const userQuery = trpc.user.me.useQuery(undefined, {
    enabled: !!user,
    retry: 1,
  });

  const handleSync = () => {
    syncMutation.mutate();
  };

  return (
    <div className="space-y-6">
      {/* Clerk User Info */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Clerk Profile</h3>
        <div className="bg-gray-50 rounded-lg p-4 space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-600">Email:</span>
            <span className="font-medium">{user?.primaryEmailAddress?.emailAddress}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">First Name:</span>
            <span className="font-medium">{user?.firstName || '-'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Last Name:</span>
            <span className="font-medium">{user?.lastName || '-'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-600">Clerk ID:</span>
            <span className="font-mono text-sm">{user?.id}</span>
          </div>
        </div>
      </div>

      {/* Database User Info */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Database Profile</h3>
        {userQuery.isLoading ? (
          <div className="bg-gray-50 rounded-lg p-4">
            <div className="animate-pulse space-y-2">
              <div className="h-4 bg-gray-200 rounded w-3/4"></div>
              <div className="h-4 bg-gray-200 rounded w-1/2"></div>
            </div>
          </div>
        ) : userQuery.error ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-600">Profile not found in database</p>
            <p className="text-sm text-red-500 mt-1">Click "Sync Profile" to create it</p>
          </div>
        ) : userQuery.data ? (
          <div className="bg-gray-50 rounded-lg p-4 space-y-2">
            <div className="flex justify-between">
              <span className="text-gray-600">Database ID:</span>
              <span className="font-mono text-sm">{userQuery.data.user.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Email:</span>
              <span className="font-medium">{userQuery.data.user.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">First Name:</span>
              <span className="font-medium">{userQuery.data.user.first_name || '-'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Last Name:</span>
              <span className="font-medium">{userQuery.data.user.last_name || '-'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Created:</span>
              <span className="text-sm">
                {new Date(userQuery.data.user.created_at).toLocaleString()}
              </span>
            </div>
          </div>
        ) : null}
      </div>

      {/* Sync Button and Status */}
      <div className="space-y-4">
        <button
          onClick={handleSync}
          disabled={status === 'loading'}
          className={`w-full py-3 px-4 rounded-lg font-medium transition-colors ${
            status === 'loading'
              ? 'bg-gray-400 cursor-not-allowed'
              : 'bg-primary-600 hover:bg-primary-700 text-white'
          }`}
        >
          {status === 'loading' ? (
            <span className="flex items-center justify-center">
              <svg
                className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
              Syncing...
            </span>
          ) : (
            'Sync Profile'
          )}
        </button>

        {message && (
          <div
            className={`p-4 rounded-lg ${
              status === 'success'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : status === 'error'
                ? 'bg-red-50 text-red-700 border border-red-200'
                : 'bg-blue-50 text-blue-700 border border-blue-200'
            }`}
          >
            {message}
          </div>
        )}
      </div>
    </div>
  );
}