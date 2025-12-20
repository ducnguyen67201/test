import { NextRequest, NextResponse } from "next/server";
import { auth } from "./auth";
import { verifyToken, getTokenFromHeader, type TokenPayload } from "./token";

export type AuthenticatedRequest = NextRequest & {
  user: TokenPayload;
};

type ApiHandler = (
  req: AuthenticatedRequest
) => Promise<NextResponse> | NextResponse;

export function withAuth(handler: ApiHandler) {
  return async (req: NextRequest): Promise<NextResponse> => {
    // First try session-based auth (NextAuth)
    const session = await auth();
    if (session?.user?.id && session?.user?.email) {
      const authenticatedReq = req as AuthenticatedRequest;
      authenticatedReq.user = {
        userId: session.user.id,
        email: session.user.email,
      };
      return handler(authenticatedReq);
    }

    // Fall back to JWT token auth
    const authHeader = req.headers.get("authorization");
    const token = getTokenFromHeader(authHeader);

    if (!token) {
      return NextResponse.json(
        { error: "Unauthorized", message: "Missing authentication token" },
        { status: 401 }
      );
    }

    const payload = await verifyToken(token);
    if (!payload) {
      return NextResponse.json(
        { error: "Unauthorized", message: "Invalid or expired token" },
        { status: 401 }
      );
    }

    const authenticatedReq = req as AuthenticatedRequest;
    authenticatedReq.user = payload;

    return handler(authenticatedReq);
  };
}
