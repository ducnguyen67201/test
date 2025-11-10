'use client';

import { useAuthenticatedUser } from '@/hooks/use-authenticated-user';
import { AuthenticatedUser } from '@/components/auth';
import { SettingsLayout } from '@/components/settings-layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';

function SettingsContent() {
  const user = useAuthenticatedUser();

  return (
    <SettingsLayout>
      <div className="space-y-6 max-w-4xl">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Profile Settings</h1>
          <p className="text-muted-foreground mt-2">
            Manage your account settings and preferences
          </p>
        </div>

        <Separator />

        <div className="space-y-6">
          {/* Personal Information */}
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold">Personal Information</h2>
              <p className="text-sm text-muted-foreground">
                Update your personal details
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="firstName">First Name</Label>
                <Input
                  id="firstName"
                  defaultValue={user.firstName || ''}
                  placeholder="Enter your first name"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="lastName">Last Name</Label>
                <Input
                  id="lastName"
                  defaultValue={user.lastName || ''}
                  placeholder="Enter your last name"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                defaultValue={user.emailAddresses[0]?.emailAddress || ''}
                disabled
                className="bg-muted"
              />
              <p className="text-xs text-muted-foreground">
                Your email is managed by your authentication provider
              </p>
            </div>
          </div>

          <Separator />

          {/* Account Information */}
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold">Account Information</h2>
              <p className="text-sm text-muted-foreground">
                View your account details
              </p>
            </div>

            <div className="rounded-lg border bg-card p-4 space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm font-medium">User ID</span>
                <span className="text-sm text-muted-foreground font-mono">{user.id}</span>
              </div>
              <Separator />
              <div className="flex justify-between items-center">
                <span className="text-sm font-medium">Account Created</span>
                <span className="text-sm text-muted-foreground">
                  {new Date(user.createdAt || '').toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })}
                </span>
              </div>
              <Separator />
              <div className="flex justify-between items-center">
                <span className="text-sm font-medium">Last Updated</span>
                <span className="text-sm text-muted-foreground">
                  {new Date(user.updatedAt || '').toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })}
                </span>
              </div>
            </div>
          </div>

          <Separator />

          {/* Actions */}
          <div className="flex gap-3">
            <Button>Save Changes</Button>
            <Button variant="outline">Cancel</Button>
          </div>
        </div>
      </div>
    </SettingsLayout>
  );
}

export default function SettingsPage() {
  return (
    <AuthenticatedUser
      accessDeniedTitle="Access Denied"
      accessDeniedMessage="Please sign in to access settings."
    >
      <SettingsContent />
    </AuthenticatedUser>
  );
}
