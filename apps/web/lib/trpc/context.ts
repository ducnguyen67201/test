import { auth } from '@clerk/nextjs/server';
import { type NextRequest } from 'next/server';

export async function createTRPCContext({ req }: { req: NextRequest }) {
  const session = await auth();

  return {
    session,
    headers: req.headers,
  };
}

export type Context = Awaited<ReturnType<typeof createTRPCContext>>;