import { AuthenticatedUser } from '@/components/auth/authenticated-user';

export default function RecipesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AuthenticatedUser>{children}</AuthenticatedUser>;
}
