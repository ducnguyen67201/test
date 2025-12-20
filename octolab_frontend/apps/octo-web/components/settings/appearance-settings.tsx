"use client";

import { useState, useEffect } from "react";
import { useTheme } from "next-themes";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Moon,
  Sun,
  Monitor,
  Check,
  Type,
  Minus,
  Plus,
  PanelLeft,
  Sparkles,
  Palette,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Theme = "light" | "dark" | "system";
type AccentColor = "orange" | "blue" | "green" | "purple" | "rose" | "zinc";
type FontSize = "small" | "default" | "large";

interface ThemeOption {
  value: Theme;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const themeOptions: ThemeOption[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

interface AccentColorOption {
  value: AccentColor;
  label: string;
  color: string;
  hoverColor: string;
}

const accentColors: AccentColorOption[] = [
  { value: "orange", label: "Orange", color: "bg-orange-500", hoverColor: "hover:ring-orange-500" },
  { value: "blue", label: "Blue", color: "bg-blue-500", hoverColor: "hover:ring-blue-500" },
  { value: "green", label: "Green", color: "bg-green-500", hoverColor: "hover:ring-green-500" },
  { value: "purple", label: "Purple", color: "bg-purple-500", hoverColor: "hover:ring-purple-500" },
  { value: "rose", label: "Rose", color: "bg-rose-500", hoverColor: "hover:ring-rose-500" },
  { value: "zinc", label: "Zinc", color: "bg-zinc-500", hoverColor: "hover:ring-zinc-500" },
];

const fontSizes: { value: FontSize; label: string }[] = [
  { value: "small", label: "Small" },
  { value: "default", label: "Default" },
  { value: "large", label: "Large" },
];

// Theme preview component
function ThemePreview({ isDark }: { isDark: boolean }) {
  return (
    <div
      className={cn(
        "rounded-lg border overflow-hidden",
        isDark ? "bg-zinc-900 border-zinc-700" : "bg-white border-zinc-200"
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "h-6 border-b flex items-center gap-1.5 px-2",
          isDark ? "bg-zinc-800 border-zinc-700" : "bg-zinc-50 border-zinc-200"
        )}
      >
        <div className="h-2 w-2 rounded-full bg-red-500" />
        <div className="h-2 w-2 rounded-full bg-yellow-500" />
        <div className="h-2 w-2 rounded-full bg-green-500" />
      </div>
      {/* Content */}
      <div className="p-2 flex gap-2">
        {/* Sidebar */}
        <div
          className={cn(
            "w-8 rounded space-y-1 p-1",
            isDark ? "bg-zinc-800" : "bg-zinc-100"
          )}
        >
          <div className={cn("h-1.5 rounded", isDark ? "bg-zinc-600" : "bg-zinc-300")} />
          <div className={cn("h-1.5 rounded", isDark ? "bg-zinc-600" : "bg-zinc-300")} />
          <div className="h-1.5 rounded bg-orange-500" />
          <div className={cn("h-1.5 rounded", isDark ? "bg-zinc-600" : "bg-zinc-300")} />
        </div>
        {/* Main */}
        <div className="flex-1 space-y-1.5">
          <div className={cn("h-2 w-16 rounded", isDark ? "bg-zinc-700" : "bg-zinc-200")} />
          <div className={cn("h-1.5 w-full rounded", isDark ? "bg-zinc-800" : "bg-zinc-100")} />
          <div className={cn("h-1.5 w-3/4 rounded", isDark ? "bg-zinc-800" : "bg-zinc-100")} />
          <div className="flex gap-1 pt-1">
            <div className="h-4 w-10 rounded bg-orange-500" />
            <div className={cn("h-4 w-10 rounded", isDark ? "bg-zinc-700" : "bg-zinc-200")} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function AppearanceSettings() {
  const [mounted, setMounted] = useState(false);
  const { theme, setTheme } = useTheme();
  const [accentColor, setAccentColor] = useState<AccentColor>("orange");
  const [fontSize, setFontSize] = useState<FontSize>("default");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [compactMode, setCompactMode] = useState(false);

  // Handle hydration
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-4 w-64 mt-2" />
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-3">
              <Skeleton className="h-32 rounded-xl" />
              <Skeleton className="h-32 rounded-xl" />
              <Skeleton className="h-32 rounded-xl" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-4 w-48 mt-2" />
          </CardHeader>
          <CardContent>
            <div className="flex gap-3">
              {[...Array(6)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-12 rounded-full" />
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-4 w-56 mt-2" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Theme Selection */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Palette className="h-5 w-5" />
            Theme
          </CardTitle>
          <CardDescription>
            Select your preferred color theme for the interface.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-3">
            {themeOptions.map((option) => {
              const isActive = theme === option.value;

              return (
                <button
                  key={option.value}
                  onClick={() => setTheme(option.value)}
                  className={cn(
                    "relative flex flex-col gap-3 rounded-xl border-2 p-3 transition-all",
                    isActive
                      ? "border-primary ring-2 ring-primary/20"
                      : "border-transparent hover:border-muted-foreground/25"
                  )}
                >
                  {/* Preview */}
                  <ThemePreview isDark={option.value === "dark"} />

                  {/* Label */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <option.icon className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium">{option.label}</span>
                    </div>
                    {isActive && (
                      <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary">
                        <Check className="h-3 w-3 text-primary-foreground" />
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Accent Color */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            Accent Color
          </CardTitle>
          <CardDescription>
            Choose the primary accent color used throughout the app.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            {accentColors.map((color) => {
              const isActive = accentColor === color.value;
              return (
                <button
                  key={color.value}
                  onClick={() => setAccentColor(color.value)}
                  className={cn(
                    "group relative flex h-12 w-12 items-center justify-center rounded-full transition-all",
                    "ring-2 ring-offset-2 ring-offset-background",
                    isActive ? "ring-foreground" : "ring-transparent hover:ring-muted-foreground/50"
                  )}
                  title={color.label}
                >
                  <span className={cn("h-8 w-8 rounded-full", color.color)} />
                  {isActive && (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Check className="h-4 w-4 text-white drop-shadow-md" />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Currently selected: <span className="font-medium capitalize">{accentColor}</span>
          </p>
        </CardContent>
      </Card>

      {/* Font Size */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Type className="h-5 w-5" />
            Font Size
          </CardTitle>
          <CardDescription>
            Adjust the base font size for better readability.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setFontSize("small")}
              disabled={fontSize === "small"}
              className="flex h-9 w-9 items-center justify-center rounded-lg border hover:bg-accent disabled:opacity-50"
            >
              <Minus className="h-4 w-4" />
            </button>

            <div className="flex flex-1 gap-2">
              {fontSizes.map((size) => {
                const isActive = fontSize === size.value;
                return (
                  <button
                    key={size.value}
                    onClick={() => setFontSize(size.value)}
                    className={cn(
                      "flex-1 rounded-lg border py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "border-primary bg-primary text-primary-foreground"
                        : "hover:bg-accent"
                    )}
                  >
                    {size.label}
                  </button>
                );
              })}
            </div>

            <button
              onClick={() => setFontSize("large")}
              disabled={fontSize === "large"}
              className="flex h-9 w-9 items-center justify-center rounded-lg border hover:bg-accent disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>

          {/* Preview */}
          <div className="mt-4 rounded-lg border bg-muted/30 p-4">
            <p
              className={cn(
                "text-muted-foreground",
                fontSize === "small" && "text-xs",
                fontSize === "default" && "text-sm",
                fontSize === "large" && "text-base"
              )}
            >
              Preview: The quick brown fox jumps over the lazy dog.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Sidebar Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PanelLeft className="h-5 w-5" />
            Sidebar
          </CardTitle>
          <CardDescription>
            Customize sidebar appearance and behavior.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="sidebar-collapsed" className="text-sm font-medium">
                Collapsed by default
              </Label>
              <p className="text-xs text-muted-foreground">
                Start with sidebar collapsed on page load
              </p>
            </div>
            <Switch
              id="sidebar-collapsed"
              checked={sidebarCollapsed}
              onCheckedChange={setSidebarCollapsed}
            />
          </div>

          <Separator />

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="compact-mode" className="text-sm font-medium">
                Compact mode
              </Label>
              <p className="text-xs text-muted-foreground">
                Reduce spacing between sidebar items
              </p>
            </div>
            <Switch
              id="compact-mode"
              checked={compactMode}
              onCheckedChange={setCompactMode}
            />
          </div>
        </CardContent>
      </Card>

      {/* Accessibility */}
      <Card>
        <CardHeader>
          <CardTitle>Accessibility</CardTitle>
          <CardDescription>
            Settings to improve your experience.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="reduce-motion" className="text-sm font-medium">
                Reduce motion
              </Label>
              <p className="text-xs text-muted-foreground">
                Minimize animations throughout the interface
              </p>
            </div>
            <Switch
              id="reduce-motion"
              checked={reduceMotion}
              onCheckedChange={setReduceMotion}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
