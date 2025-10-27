import { auth } from '@clerk/nextjs';
import { type NextRequest } from 'next/server';

export async function createTRPCContext({ req }: { req: NextRequest }) {
  const session = auth();

  return {
    session,
    headers: req.headers,
  };
}

export type Context = Awaited<ReturnType<typeof createTRPCContext>>;