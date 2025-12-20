"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function ErrorContent() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

  const errorMessages: Record<string, string> = {
    Configuration: "There is a problem with the server configuration.",
    AccessDenied: "Access denied. You do not have permission to sign in.",
    Verification: "The verification link has expired or has already been used.",
    Default: "An error occurred during authentication.",
  };

  const message = errorMessages[error ?? "Default"] ?? errorMessages.Default;

  return (
    <div className="w-full max-w-md space-y-6 rounded-lg border p-8 shadow-lg">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-red-600">
          Authentication Error
        </h1>
        <p className="mt-2 text-gray-600">{message}</p>
      </div>

      <Link
        href="/auth/signin"
        className="block w-full rounded-md bg-gray-900 px-4 py-2 text-center text-white hover:bg-gray-800"
      >
        Try again
      </Link>
    </div>
  );
}

export default function AuthErrorPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Suspense
        fallback={
          <div className="w-full max-w-md p-8 text-center">Loading...</div>
        }
      >
        <ErrorContent />
      </Suspense>
    </div>
  );
}
