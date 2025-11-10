'use client';

import * as React from 'react';
import {
  User,
  Building2,
  Key,
  Bell,
  Webhook,
  Puzzle,
  Gauge,
  Hash,
  SlidersHorizontal,
  ArrowLeft,
  Sun,
  Monitor,
  Moon,
} from 'lucide-react';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { useTheme } from 'next-themes';
import { useUser } from '@clerk/nextjs';

const settingsItems = [
  {
    title: 'Profile',
    url: '/settings',
    icon: User,
  },
  {
    title: 'Workspaces',
    url: '/settings/workspaces',
    icon: Building2,
  },
  {
    title: 'API Keys',
    url: '/settings/api-keys',
    icon: Key,
  },
  {
    title: 'Notifications',
    url: '/settings/notifications',
    icon: Bell,
  },
  {
    title: 'Webhooks',
    url: '/settings/webhooks',
    icon: Webhook,
  },
  {
    title: 'Integrations',
    url: '/settings/integrations',
    icon: Puzzle,
  },
  {
    title: 'Rate Limit',
    url: '/settings/rate-limit',
    icon: Gauge,
  },
  {
    title: 'Numbers',
    url: '/settings/numbers',
    icon: Hash,
  },
  {
    title: 'Metrics Thresholds',
    url: '/settings/metrics',
    icon: SlidersHorizontal,
  },
];

export function SettingsSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { theme, setTheme } = useTheme();
  const { user } = useUser();

  return (
    <Sidebar {...props}>
      <SidebarHeader className="border-b border-sidebar-border px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <span className="text-sm font-bold">ZZ</span>
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold">ZeroZero</span>
            <span className="text-xs text-muted-foreground">v0.5</span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild>
                  <a href="/" className="font-medium">
                    <ArrowLeft className="h-4 w-4" />
                    <span>Back to App</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {settingsItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild>
                    <a href={item.url}>
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border p-4">
        <div className="flex items-center justify-center gap-1 rounded-md bg-muted p-1">
          <Button
            variant={theme === 'light' ? 'default' : 'ghost'}
            size="icon"
            onClick={() => setTheme('light')}
            className="h-8 w-8"
            title="Light mode"
          >
            <Sun className="h-4 w-4" />
          </Button>
          <Button
            variant={theme === 'system' ? 'default' : 'ghost'}
            size="icon"
            onClick={() => setTheme('system')}
            className="h-8 w-8"
            title="System mode"
          >
            <Monitor className="h-4 w-4" />
          </Button>
          <Button
            variant={theme === 'dark' ? 'default' : 'ghost'}
            size="icon"
            onClick={() => setTheme('dark')}
            className="h-8 w-8"
            title="Dark mode"
          >
            <Moon className="h-4 w-4" />
          </Button>
        </div>

        {user && (
          <div className="mt-4 flex items-center gap-3 rounded-lg border bg-card p-3">
            <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
              <span className="text-sm font-semibold text-primary">
                {user.firstName?.charAt(0) || user.emailAddresses[0].emailAddress.charAt(0).toUpperCase()}
              </span>
            </div>
            <div className="flex flex-col overflow-hidden">
              <span className="text-sm font-medium truncate">
                {user.firstName || 'User'} {user.lastName || ''}
              </span>
              <span className="text-xs text-muted-foreground truncate">
                {user.emailAddresses[0].emailAddress}
              </span>
            </div>
          </div>
        )}
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
