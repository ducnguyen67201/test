"use client";

import { TrendingUp, TrendingDown, Users, FileText, Activity, DollarSign } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface StatCardProps {
  title: string;
  value: string;
  change: string;
  changeType: "positive" | "negative";
  icon: React.ComponentType<{ className?: string }>;
}

function StatCard({ title, value, change, changeType, icon: Icon }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <div className="flex items-center gap-1 text-xs">
          <Badge
            variant={changeType === "positive" ? "default" : "destructive"}
            className="gap-1 px-1.5"
          >
            {changeType === "positive" ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {change}
          </Badge>
          <span className="text-muted-foreground">from last month</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function OverviewCards() {
  const stats: StatCardProps[] = [
    {
      title: "Total Revenue",
      value: "$45,231.89",
      change: "+20.1%",
      changeType: "positive",
      icon: DollarSign,
    },
    {
      title: "Subscriptions",
      value: "+2,350",
      change: "+180.1%",
      changeType: "positive",
      icon: Users,
    },
    {
      title: "Active Users",
      value: "+12,234",
      change: "+19%",
      changeType: "positive",
      icon: Activity,
    },
    {
      title: "Documents",
      value: "+573",
      change: "-4%",
      changeType: "negative",
      icon: FileText,
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <StatCard key={stat.title} {...stat} />
      ))}
    </div>
  );
}
