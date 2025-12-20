import "server-only";
import { headers } from "next/headers";
import { cache } from "react";
import { createCaller } from "./root";
import { createTRPCContext } from "./init";

/**
 * Server-side tRPC caller for use in Server Components
 * Cached per request to avoid duplicate context creation
 *
 * @example
 * // In a Server Component
 * import { api } from "@/lib/trpc/server";
 *
 * export default async function Page() {
 *   const user = await api.user.me();
 *   return <div>{user?.name}</div>;
 * }
 */
export const api = cache(async () => {
  const heads = await headers();
  const context = await createTRPCContext({
    headers: heads,
  });
  return createCaller(context);
});
