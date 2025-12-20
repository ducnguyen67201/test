"use client";

import Image from "next/image";
import { useSession, signOut } from "next-auth/react";

export function UserNav() {
  const { data: session } = useSession();

  if (!session?.user) return null;

  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2">
        {session.user.image && (
          <Image
            src={session.user.image}
            alt={session.user.name ?? "User"}
            width={32}
            height={32}
            className="h-8 w-8 rounded-full"
          />
        )}
        <span className="text-sm font-medium">
          {session.user.name ?? session.user.email}
        </span>
      </div>
      <button
        onClick={() => signOut({ callbackUrl: "/auth/signin" })}
        className="rounded-md bg-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-300"
      >
        Sign out
      </button>
    </div>
  );
}
