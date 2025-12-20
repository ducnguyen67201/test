import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OverviewCards } from "@/components/dashboard/overview-cards";
import { OverviewChart } from "@/components/dashboard/overview-chart";
import { RecentActivity } from "@/components/dashboard/recent-activity";

export default function HomePage() {
  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-muted-foreground">
          Welcome back! Here&apos;s an overview of your activity.
        </p>
      </div>

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="analytics">Analytics</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <OverviewCards />

          <div className="grid gap-6 lg:grid-cols-7">
            <div className="lg:col-span-4">
              <OverviewChart />
            </div>
            <div className="lg:col-span-3">
              <RecentActivity />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="analytics">
          <div className="flex h-[400px] items-center justify-center rounded-lg border border-dashed">
            <p className="text-muted-foreground">Analytics content coming soon</p>
          </div>
        </TabsContent>

        <TabsContent value="reports">
          <div className="flex h-[400px] items-center justify-center rounded-lg border border-dashed">
            <p className="text-muted-foreground">Reports content coming soon</p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
