'use client';

import * as React from 'react';
import {
  Home,
  Settings,
  Users,
  LayoutDashboard,
  FileText,
  HelpCircle,
  ChevronRight,
  LogOut,
  User,
  Moon,
  Sun,
  Monitor,
  FlaskConical,
} from 'lucide-react';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { useUser, useClerk } from '@clerk/nextjs';
import { Button } from '@/components/ui/button';
import { useTheme } from 'next-themes';

const navItems = [
  {
    title: 'Dashboard',
    url: '/',
    icon: LayoutDashboard,
  },
  {
    title: 'Home',
    url: '/home',
    icon: Home,
  },
  {
    title: 'Labs',
    url: '/labs/request',
    icon: FlaskConical,
  },
  {
    title: 'Users',
    url: '/users',
    icon: Users,
  },
  {
    title: 'Documents',
    url: '/documents',
    icon: FileText,
  },
];

const bottomNavItems = [
  {
    title: 'Settings',
    url: '/settings',
    icon: Settings,
  },
  {
    title: 'Help',
    url: '/help',
    icon: HelpCircle,
  },
];

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { user } = useUser();
  const { toggleSidebar, state } = useSidebar();
  const { theme, setTheme } = useTheme();
  const { signOut } = useClerk();
  const [mounted, setMounted] = React.useState(false);

  // Only render theme buttons after mounting to avoid hydration mismatch
  React.useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader className="border-b border-sidebar-border px-4 py-3 group-data-[collapsible=icon]:px-2">
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={toggleSidebar}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shrink-0">
              <span className="text-sm font-bold">ZZ</span>
            </div>
            <div className="flex flex-col group-data-[collapsible=icon]:hidden">
              <span className="text-sm font-semibold">ZeroZero</span>
              <span className="text-xs text-muted-foreground">Production Ready</span>
            </div>
          </button>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            className="ml-auto h-7 w-7 group-data-[collapsible=icon]:hidden"
          >
            <ChevronRight className={`h-4 w-4 transition-transform ${state === 'expanded' ? 'rotate-180' : ''}`} />
            <span className="sr-only">Toggle Sidebar</span>
          </Button>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild tooltip={item.title}>
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

      <SidebarFooter className="border-t border-sidebar-border">
        <SidebarMenu>
          {bottomNavItems.map((item) => {
            if (item.title === 'Settings') {
              return (
                <SidebarMenuItem key={item.title}>
                  <div className="flex items-center gap-2 group-data-[collapsible=icon]:gap-0">
                    <SidebarMenuButton asChild tooltip={item.title} className="group-data-[collapsible=icon]:flex-none">
                      <a href={item.url}>
                        <item.icon className="h-4 w-4" />
                        <span>{item.title}</span>
                      </a>
                    </SidebarMenuButton>
                    {mounted && (
                      <div className="flex items-center rounded-md bg-muted p-1 group-data-[collapsible=icon]:hidden">
                        <Button
                          variant={theme === 'light' ? 'default' : 'ghost'}
                          size="icon"
                          onClick={() => setTheme('light')}
                          className="h-6 w-6"
                          title="Light mode"
                        >
                          <Sun className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant={theme === 'system' ? 'default' : 'ghost'}
                          size="icon"
                          onClick={() => setTheme('system')}
                          className="h-6 w-6"
                          title="System mode"
                        >
                          <Monitor className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant={theme === 'dark' ? 'default' : 'ghost'}
                          size="icon"
                          onClick={() => setTheme('dark')}
                          className="h-6 w-6"
                          title="Dark mode"
                        >
                          <Moon className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}
                  </div>
                </SidebarMenuItem>
              );
            }
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton asChild tooltip={item.title}>
                  <a href={item.url}>
                    <item.icon className="h-4 w-4" />
                    <span>{item.title}</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>

        {user && (
          <>
            {/* Expanded state: User info with logout button */}
            <div className="px-4 py-3 border-t border-sidebar-border group-data-[collapsible=icon]:hidden">
              <div className="flex items-center gap-3 rounded-md p-2 -mx-2">
                <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <span className="text-xs font-semibold text-primary">
                    {user.firstName?.charAt(0) || user.emailAddresses[0].emailAddress.charAt(0).toUpperCase()}
                  </span>
                </div>
                <div className="flex flex-col overflow-hidden flex-1">
                  <span className="text-sm font-medium truncate">
                    {user.firstName || 'User'}
                  </span>
                  <span className="text-xs text-muted-foreground truncate">
                    {user.emailAddresses[0].emailAddress}
                  </span>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      title="Sign out"
                    >
                      <LogOut className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Are you sure you want to sign out?</AlertDialogTitle>
                      <AlertDialogDescription>
                        You will be logged out of your account and redirected to the home page.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => signOut()}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Sign out
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>

            {/* Collapsed state: Click to expand sidebar */}
            <div className="hidden group-data-[collapsible=icon]:block px-2 py-3 border-t border-sidebar-border">
              <button
                onClick={toggleSidebar}
                className="flex items-center justify-center w-full hover:bg-sidebar-accent rounded-md p-2 transition-colors"
              >
                <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <span className="text-xs font-semibold text-primary">
                    {user.firstName?.charAt(0) || user.emailAddresses[0].emailAddress.charAt(0).toUpperCase()}
                  </span>
                </div>
              </button>
            </div>
          </>
        )}

        <div className="hidden group-data-[collapsible=icon]:block px-2 pb-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            className="w-full h-10 rounded-md hover:bg-sidebar-accent"
          >
            <ChevronRight className="h-4 w-4" />
            <span className="sr-only">Expand Sidebar</span>
          </Button>
        </div>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
