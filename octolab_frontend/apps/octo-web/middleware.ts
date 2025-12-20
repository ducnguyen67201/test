import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

const publicRoutes = ["/auth/signin", "/auth/signup", "/auth/error", "/auth/forgot-password"];
const authRoutes = ["/auth/signin", "/auth/signup", "/auth/forgot-password"];

export default auth((req) => {
  const { nextUrl } = req;
  const isLoggedIn = !!req.auth;
  const isPublicRoute = publicRoutes.includes(nextUrl.pathname);
  const isAuthRoute = authRoutes.includes(nextUrl.pathname);
  const isAdminRoute = nextUrl.pathname.startsWith("/admin");

  // Redirect logged-in users from auth pages to home
  if (isLoggedIn && isAuthRoute) {
    return NextResponse.redirect(new URL("/", nextUrl));
  }

  // Redirect unauthenticated users to sign-in (except public routes)
  if (!isLoggedIn && !isPublicRoute) {
    const signInUrl = new URL("/auth/signin", nextUrl);
    signInUrl.searchParams.set("callbackUrl", nextUrl.pathname);
    return NextResponse.redirect(signInUrl);
  }

  // Block non-admin users from admin routes
  if (isAdminRoute && isLoggedIn) {
    const isSystemAdmin = req.auth?.user?.isSystemAdmin ?? false;
    if (!isSystemAdmin) {
      return NextResponse.redirect(new URL("/", nextUrl));
    }
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
