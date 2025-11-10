'use client';

import { useAuthenticatedUser } from '@/hooks/use-authenticated-user';
import { AuthenticatedUser } from '@/components/auth';
import { DashboardLayout } from '@/components/dashboard-layout';
import { Button } from '@/components/ui/button';
import { ArrowRight, Zap, Shield, Code2, Database } from 'lucide-react';

function HomeContent() {
  const user = useAuthenticatedUser();

  return (
    <DashboardLayout>
      <div className="space-y-8">
        {/* Welcome Section */}
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Welcome back, {user.firstName || 'User'}!
          </h1>
          <p className="text-muted-foreground mt-2">
            Your production-ready monorepo dashboard
          </p>
        </div>

        {/* Quick Stats */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border bg-card p-6">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-lg bg-primary/10">
                <Zap className="h-4 w-4 text-primary" />
              </div>
              <h3 className="font-semibold">Fast Development</h3>
            </div>
            <p className="text-2xl font-bold">Next.js 16</p>
            <p className="text-xs text-muted-foreground mt-1">
              With Turbopack & React 19
            </p>
          </div>

          <div className="rounded-lg border bg-card p-6">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-lg bg-primary/10">
                <Shield className="h-4 w-4 text-primary" />
              </div>
              <h3 className="font-semibold">Type Safety</h3>
            </div>
            <p className="text-2xl font-bold">100%</p>
            <p className="text-xs text-muted-foreground mt-1">
              Full TypeScript coverage
            </p>
          </div>

          <div className="rounded-lg border bg-card p-6">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-lg bg-primary/10">
                <Code2 className="h-4 w-4 text-primary" />
              </div>
              <h3 className="font-semibold">Clean Architecture</h3>
            </div>
            <p className="text-2xl font-bold">Go Backend</p>
            <p className="text-xs text-muted-foreground mt-1">
              DDD & Clean Code
            </p>
          </div>

          <div className="rounded-lg border bg-card p-6">
            <div className="flex items-center gap-2 mb-2">
              <div className="p-2 rounded-lg bg-primary/10">
                <Database className="h-4 w-4 text-primary" />
              </div>
              <h3 className="font-semibold">PostgreSQL</h3>
            </div>
            <p className="text-2xl font-bold">Ready</p>
            <p className="text-xs text-muted-foreground mt-1">
              With migrations & sqlc
            </p>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="rounded-lg border bg-card p-6">
          <h2 className="text-xl font-semibold mb-4">Quick Actions</h2>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            <Button variant="outline" className="justify-start" asChild>
              <a href="/settings">
                <ArrowRight className="mr-2 h-4 w-4" />
                Profile Settings
              </a>
            </Button>
            <Button variant="outline" className="justify-start" asChild>
              <a href="/documents">
                <ArrowRight className="mr-2 h-4 w-4" />
                Browse Documents
              </a>
            </Button>
            <Button variant="outline" className="justify-start" asChild>
              <a href="/help">
                <ArrowRight className="mr-2 h-4 w-4" />
                Help & Support
              </a>
            </Button>
          </div>
        </div>

        {/* Getting Started */}
        <div className="rounded-lg border bg-card p-6">
          <h2 className="text-xl font-semibold mb-4">Getting Started</h2>
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                1
              </div>
              <div>
                <h3 className="font-semibold">Explore the Architecture</h3>
                <p className="text-sm text-muted-foreground">
                  Check out the clean separation between frontend and backend
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                2
              </div>
              <div>
                <h3 className="font-semibold">Review the Tech Stack</h3>
                <p className="text-sm text-muted-foreground">
                  Modern tools: Next.js, Go, PostgreSQL, tRPC, and more
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                3
              </div>
              <div>
                <h3 className="font-semibold">Build Your Features</h3>
                <p className="text-sm text-muted-foreground">
                  Start adding your own features on top of this solid foundation
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

export default function HomePage() {
  return (
    <AuthenticatedUser
      accessDeniedTitle="Welcome to ZeroZero"
      accessDeniedMessage="A production-ready monorepo demonstrating Clean Architecture, type-safe APIs, and modern authentication."
    >
      <HomeContent />
    </AuthenticatedUser>
  );
}