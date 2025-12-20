import { NextResponse } from "next/server";
import { withAuth, type AuthenticatedRequest } from "@/lib/api-auth";

export const GET = withAuth(async (req: AuthenticatedRequest) => {
  return NextResponse.json({
    user: req.user,
  });
});
