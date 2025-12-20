import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

/**
 * GET /api/labs/[id]/connect
 *
 * Authenticated proxy to connect to a lab via Guacamole.
 * This endpoint:
 * 1. Verifies user is authenticated via NextAuth
 * 2. Verifies user owns the lab
 * 3. Calls the OctoLab MVP backend to get the Guacamole redirect URL
 * 4. Redirects the user to Guacamole
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: labId } = await params;

  // Check authentication (NextAuth v5 pattern)
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401 }
    );
  }

  // Look up the lab
  const lab = await prisma.lab.findUnique({
    where: { id: labId },
  });

  if (!lab) {
    return NextResponse.json(
      { error: "Lab not found" },
      { status: 404 }
    );
  }

  // Verify ownership
  if (lab.ownerId !== session.user.id) {
    return NextResponse.json(
      { error: "Lab not found" },
      { status: 404 }
    );
  }

  // Check lab is ready
  if (lab.status !== "ready") {
    return NextResponse.json(
      { error: `Lab is not ready (status: ${lab.status})` },
      { status: 409 }
    );
  }

  // Extract backend lab ID from connectionUrl
  // URL format: http://host:port/labs/{backendLabId}/connect
  if (!lab.connectionUrl) {
    return NextResponse.json(
      { error: "Lab has no connection URL" },
      { status: 500 }
    );
  }

  const urlMatch = lab.connectionUrl.match(/\/labs\/([^/]+)\/connect/);
  if (!urlMatch) {
    return NextResponse.json(
      { error: "Invalid connection URL format" },
      { status: 500 }
    );
  }

  const backendLabId = urlMatch[1];
  const octoLabBaseUrl = process.env.OCTOLAB_MVP_URL ?? "http://localhost:8000";

  try {
    // Call backend POST /connect to get the redirect URL
    const response = await fetch(`${octoLabBaseUrl}/labs/${backendLabId}/connect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(process.env.OCTOLAB_SERVICE_TOKEN && {
          "X-Service-Token": process.env.OCTOLAB_SERVICE_TOKEN,
          "X-User-Email": session.user.email ?? "",
        }),
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
      console.error("Backend connect failed:", errorData);
      return NextResponse.json(
        { error: errorData.detail || `Backend error: ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();

    // Backend returns { redirect_url: "..." }
    if (data.redirect_url) {
      let redirectUrl = data.redirect_url;

      // Handle relative URLs (e.g., /guacamole/...) - make them absolute
      if (redirectUrl.startsWith("/")) {
        const publicBaseUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://34.151.112.15";
        redirectUrl = `${publicBaseUrl}${redirectUrl}`;
      }
      // Handle localhost URLs - replace with public URL
      else if (redirectUrl.includes("127.0.0.1") || redirectUrl.includes("localhost")) {
        const publicUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://34.151.112.15";
        redirectUrl = redirectUrl.replace(/http:\/\/(localhost|127\.0\.0\.1)(:\d+)?/, publicUrl);
      }

      return NextResponse.redirect(redirectUrl, 302);
    }

    return NextResponse.json(
      { error: "No redirect URL returned from backend" },
      { status: 500 }
    );
  } catch (error) {
    console.error("Error connecting to lab:", error);
    return NextResponse.json(
      { error: "Failed to connect to lab service" },
      { status: 503 }
    );
  }
}
