import { SettingsNav } from "@/components/settings/settings-nav";
import { Separator } from "@/components/ui/separator";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Settings</h2>
        <p className="text-muted-foreground">
          Manage your account settings and preferences.
        </p>
      </div>

      <Separator />

      <div className="flex flex-col gap-8 lg:flex-row lg:gap-12">
        {/* Sub-sidebar */}
        <aside className="lg:w-48 shrink-0">
          <SettingsNav />
        </aside>

        {/* Content */}
        <div className="flex-1 max-w-3xl">{children}</div>
      </div>
    </div>
  );
}
