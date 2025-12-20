import { DefaultSession, DefaultUser } from "next-auth";
import { DefaultJWT } from "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      isSystemAdmin: boolean;
    } & DefaultSession["user"];
  }

  interface User extends DefaultUser {
    isSystemAdmin: boolean;
  }
}

declare module "next-auth/jwt" {
  interface JWT extends DefaultJWT {
    isSystemAdmin?: boolean;
  }
}
