import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { createToken } from "@/lib/token";

export async function GET() {
  const session = await auth();

  if (!session?.user?.id || !session?.user?.email) {
    return NextResponse.json(
      { error: "Unauthorized", message: "You must be signed in" },
      { status: 401 }
    );
  }

  const token = await createToken({
    userId: session.user.id,
    email: session.user.email,
  });

  return NextResponse.json({ token });
}
