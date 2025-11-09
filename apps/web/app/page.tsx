'use client';

import { useUser, SignInButton } from '@clerk/nextjs';
import { DashboardLayout } from '@/components/dashboard-layout';
import { ProfileSync } from '@/components/ProfileSync';
import { TestApiButton } from '@/components/TestApiButton';
import { Button } from '@/components/ui/button';

export default function HomePage() {
  const { isLoaded, isSignedIn, user } = useUser();

  if (!isLoaded) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!isSignedIn) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="max-w-md w-full mx-4">
          <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-8 text-center">
            <h2 className="text-3xl font-bold mb-4">Welcome to ZeroZero</h2>
            <p className="text-muted-foreground mb-6">
              A production-ready monorepo demonstrating Clean Architecture,
              type-safe APIs, and modern authentication.
            </p>
            <SignInButton mode="modal">
              <Button size="lg" className="w-full">
                Get Started
              </Button>
            </SignInButton>
          </div>
        </div>
      </div>
    );
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Welcome back, {user.firstName || 'User'}!
          </h2>
          <p className="text-muted-foreground">
            Here's what's happening with your projects today.
          </p>
        </div>

        <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
          <h3 className="text-xl font-semibold mb-4">Profile Management</h3>
          <ProfileSync />
        </div>

        <TestApiButton />

        <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
          <h3 className="text-xl font-semibold mb-4">System Architecture</h3>
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <h4 className="font-semibold text-primary mb-3">Backend (Go)</h4>
              <ul className="text-sm text-muted-foreground space-y-2">
                <li>• Clean Architecture with DDD</li>
                <li>• Connect gRPC server</li>
                <li>• Gin HTTP framework</li>
                <li>• PostgreSQL with sqlc</li>
                <li>• Clerk JWT authentication</li>
              </ul>
            </div>
            <div>
              <h4 className="font-semibold text-primary mb-3">Frontend (Next.js)</h4>
              <ul className="text-sm text-muted-foreground space-y-2">
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
    </DashboardLayout>
  );
}