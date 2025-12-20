"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ActivityItem {
  id: string;
  user: {
    name: string;
    email: string;
    avatar?: string;
  };
  action: string;
  timestamp: string;
}

const recentActivity: ActivityItem[] = [
  {
    id: "1",
    user: { name: "Olivia Martin", email: "olivia.martin@email.com" },
    action: "Created new project",
    timestamp: "2 hours ago",
  },
  {
    id: "2",
    user: { name: "Jackson Lee", email: "jackson.lee@email.com" },
    action: "Updated settings",
    timestamp: "3 hours ago",
  },
  {
    id: "3",
    user: { name: "Isabella Nguyen", email: "isabella.nguyen@email.com" },
    action: "Deployed to production",
    timestamp: "5 hours ago",
  },
  {
    id: "4",
    user: { name: "William Kim", email: "will@email.com" },
    action: "Invited team member",
    timestamp: "1 day ago",
  },
  {
    id: "5",
    user: { name: "Sofia Davis", email: "sofia.davis@email.com" },
    action: "Completed onboarding",
    timestamp: "2 days ago",
  },
];

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

export function RecentActivity() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Activity</CardTitle>
        <CardDescription>Latest actions from your team</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {recentActivity.map((item) => (
            <div key={item.id} className="flex items-center gap-4">
              <Avatar className="h-9 w-9">
                <AvatarImage src={item.user.avatar} alt={item.user.name} />
                <AvatarFallback>{getInitials(item.user.name)}</AvatarFallback>
              </Avatar>
              <div className="flex-1 space-y-1">
                <p className="text-sm font-medium leading-none">
                  {item.user.name}
                </p>
                <p className="text-sm text-muted-foreground">{item.action}</p>
              </div>
              <div className="text-xs text-muted-foreground">
                {item.timestamp}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
