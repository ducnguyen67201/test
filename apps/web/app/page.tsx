'use client';

import { useUser, SignInButton, SignOutButton } from '@clerk/nextjs';
import { ProfileSync } from '@/components/ProfileSync';
import { TestGrpcButton } from '@/components/TestGrpcButton';

export default function HomePage() {
  const { isLoaded, isSignedIn, user } = useUser();

  if (!isLoaded) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 to-primary-100">
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <h1 className="text-2xl font-bold text-primary-600">ZeroZero</h1>
            <div>
              {isSignedIn ? (
                <div className="flex items-center space-x-4">
                  <span className="text-gray-700">
                    Welcome, {user.firstName || user.emailAddresses[0].emailAddress}!
                  </span>
                  <SignOutButton>
                    <button className="btn-secondary">Sign Out</button>
                  </SignOutButton>
                </div>
              ) : (
                <SignInButton mode="modal">
                  <button className="btn-primary">Sign In</button>
                </SignInButton>
              )}
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {isSignedIn ? (
          <div className="space-y-8">
            <div className="card">
              <h2 className="text-2xl font-bold mb-4">Profile Management</h2>
              <ProfileSync />
            </div>

            <TestGrpcButton />

            <div className="card">
              <h2 className="text-xl font-semibold mb-4">System Architecture</h2>
              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <h3 className="font-semibold text-primary-600 mb-2">Backend (Go)</h3>
                  <ul className="text-sm text-gray-600 space-y-1">
                    <li>• Clean Architecture with DDD</li>
                    <li>• Connect gRPC server</li>
                    <li>• Gin HTTP framework</li>
                    <li>• PostgreSQL with sqlc</li>
                    <li>• Clerk JWT authentication</li>
                  </ul>
                </div>
                <div>
                  <h3 className="font-semibold text-primary-600 mb-2">Frontend (Next.js)</h3>
                  <ul className="text-sm text-gray-600 space-y-1">
                    <li>• App Router with Server Components</li>
                    <li>• tRPC for type-safe APIs</li>
                    <li>• Connect-Web gRPC client</li>
                    <li>• Clerk authentication</li>
                    <li>• Tailwind CSS styling</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="card text-center">
            <h2 className="text-3xl font-bold mb-4">Welcome to ZeroZero</h2>
            <p className="text-gray-600 mb-6">
              A production-ready monorepo demonstrating Clean Architecture,
              type-safe APIs, and modern authentication.
            </p>
            <SignInButton mode="modal">
              <button className="btn-primary text-lg px-8 py-3">
                Get Started
              </button>
            </SignInButton>
          </div>
        )}
      </main>
    </div>
  );
}