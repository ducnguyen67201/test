"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Mail, Lock, Github, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";

export default function SignInPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";
  const error = searchParams.get("error");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setFormError(null);

    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        setFormError("Invalid email or password");
      } else {
        router.push(callbackUrl);
        router.refresh();
      }
    } catch {
      setFormError("Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* Left Side - Sign In Form */}
      <div className="flex w-full flex-col justify-center px-8 lg:w-1/2 lg:px-16 xl:px-24">
        <div className="mx-auto w-full max-w-md">
          {/* Logo */}
          <div className="mb-8">
            <div className="flex items-center gap-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-foreground">
                <span className="text-xl font-bold text-background">O</span>
              </div>
              <span className="text-xl font-semibold">OctoLab</span>
            </div>
          </div>

          {/* Title */}
          <h1 className="mb-8 text-3xl font-bold">Sign in</h1>

          {/* Error Messages */}
          {(formError || error) && (
            <div className="mb-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {formError || "Authentication failed. Please try again."}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Email */}
            <div className="space-y-2">
              <Label htmlFor="email">Email Address</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  placeholder="johndoe@gmail.com"
                  className="pl-10"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Password */}
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  className="pl-10"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Remember Me */}
            <div className="flex items-center space-x-2">
              <Checkbox id="remember" />
              <Label htmlFor="remember" className="text-sm font-normal">
                Remember me
              </Label>
            </div>

            {/* Sign In Button */}
            <Button type="submit" className="w-full" size="lg" disabled={isLoading}>
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>

          {/* Links */}
          <div className="mt-6 space-y-2 text-sm">
            <p className="text-muted-foreground">
              Don&apos;t have an account?{" "}
              <Link
                href="/auth/signup"
                className="font-medium text-foreground underline-offset-4 hover:underline"
              >
                Sign up
              </Link>
            </p>
            <Link
              href="/auth/forgot-password"
              className="block text-muted-foreground hover:text-foreground"
            >
              Forgot Password
            </Link>
          </div>

          {/* Social Login */}
          <div className="mt-8 flex items-center gap-4">
            <Button
              variant="outline"
              size="icon"
              className="h-12 w-12 rounded-full"
              onClick={() => signIn("google", { callbackUrl })}
              disabled={isLoading}
            >
              <svg className="h-5 w-5" viewBox="0 0 24 24">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-12 w-12 rounded-full"
              onClick={() => signIn("github", { callbackUrl })}
              disabled={isLoading}
            >
              <Github className="h-5 w-5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-12 w-12 rounded-full"
              disabled={isLoading}
            >
              <svg className="h-5 w-5" fill="#1877F2" viewBox="0 0 24 24">
                <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
              </svg>
            </Button>
          </div>
        </div>
      </div>

      {/* Right Side - Promotional Panel */}
      <div className="hidden lg:flex lg:w-1/2 lg:items-center lg:justify-center lg:bg-muted/30 lg:p-8">
        <div className="relative h-full w-full max-w-xl overflow-hidden rounded-3xl bg-gradient-to-br from-zinc-900 to-zinc-800 p-8 text-white">
          {/* Background Logo */}
          <div className="absolute -right-20 -top-20 text-[400px] font-bold leading-none text-zinc-800/50">
            O
          </div>

          {/* Decorative Lines */}
          <div className="absolute right-0 top-0 h-full w-1/2">
            <div className="absolute right-10 top-20 h-[400px] w-px rotate-[30deg] bg-gradient-to-b from-transparent via-zinc-600 to-transparent" />
            <div className="absolute right-20 top-10 h-[400px] w-px rotate-[30deg] bg-gradient-to-b from-transparent via-zinc-700 to-transparent" />
          </div>

          {/* Content */}
          <div className="relative z-10 flex h-full flex-col justify-center">
            <p className="text-sm font-medium text-zinc-400">OctoLab</p>
            <h2 className="mt-2 text-4xl font-bold">Welcome to OctoLab</h2>
            <p className="mt-4 max-w-sm text-zinc-400">
              OctoLab helps developers to build organized and well coded
              dashboards full of beautiful and rich modules. Join us and start
              building your application today.
            </p>
            <p className="mt-6 text-sm text-zinc-300">
              More than 17k people joined us, it&apos;s your turn
            </p>

            {/* CTA Card */}
            <div className="mt-8 rounded-2xl bg-zinc-800/80 p-6 backdrop-blur">
              <h3 className="text-xl font-bold">
                Get your right job and right place apply now
              </h3>
              <p className="mt-2 text-sm text-zinc-400">
                Be among the first founders to experience the easiest way to
                start run a business.
              </p>
              <div className="mt-4 flex items-center">
                <div className="flex -space-x-2">
                  <div className="h-8 w-8 rounded-full bg-zinc-600 ring-2 ring-zinc-800" />
                  <div className="h-8 w-8 rounded-full bg-zinc-500 ring-2 ring-zinc-800" />
                  <div className="h-8 w-8 rounded-full bg-zinc-400 ring-2 ring-zinc-800" />
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground ring-2 ring-zinc-800">
                    +2
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Indicator */}
          <div className="absolute bottom-4 left-1/2 h-1 w-16 -translate-x-1/2 rounded-full bg-zinc-600" />
        </div>
      </div>
    </div>
  );
}
