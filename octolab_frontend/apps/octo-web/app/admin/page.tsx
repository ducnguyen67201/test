"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/trpc/react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Users,
  Shield,
  ShieldOff,
  Search,
  MoreHorizontal,
  UserX,
  RefreshCw,
  FileCode,
  Flag,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

// Review item type
interface ReviewItem {
  id: string;
  cve_id: string;
  recipe_name: string;
  last_dockerfile: string | null;
  errors: string[];
  attempts: number;
  status: string;
  confidence_score: number | null;
  confidence_reason: string | null;
  created_at: string | null;
}

export default function AdminPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");

  // User management queries
  const { data: usersData, isLoading, refetch } = api.admin.listUsers.useQuery({
    search: searchQuery || undefined,
    limit: 50,
  });
  const users = usersData?.users;

  const { data: stats } = api.admin.getStats.useQuery();

  // Review queue queries
  const { data: reviewQueue, isLoading: reviewLoading, refetch: refetchReviews } =
    api.admin.listReviewQueue.useQuery({ status: "pending", limit: 50 });

  // Lab reports queries
  const { data: labReportStats } = api.labReport.stats.useQuery();
  const { data: labReports, isLoading: reportsLoading, refetch: refetchReports } =
    api.labReport.list.useQuery({ status: undefined, limit: 50 });

  const toggleAdminMutation = api.admin.toggleSystemAdmin.useMutation({
    onSuccess: () => {
      refetch();
    },
  });

  const restrictUserMutation = api.admin.restrictUser.useMutation({
    onSuccess: () => {
      refetch();
    },
  });

  const getInitials = (name?: string | null): string => {
    if (!name) return "U";
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2);
  };

  const handleReviewClick = (item: ReviewItem) => {
    router.push(`/admin/review/${item.id}`);
  };

  const handleReportClick = (recipeId: string) => {
    router.push(`/admin/lab-reports/${recipeId}`);
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Admin Dashboard</h2>
        <p className="text-muted-foreground">
          Manage users and system settings.
        </p>
      </div>

      <Tabs defaultValue="users" className="space-y-4">
        <TabsList>
          <TabsTrigger value="users" className="gap-2">
            <Users className="h-4 w-4" />
            Users
          </TabsTrigger>
          <TabsTrigger value="review" className="gap-2">
            <FileCode className="h-4 w-4" />
            Dockerfile Review
            {reviewQueue && reviewQueue.length > 0 && (
              <Badge variant="secondary" className="ml-1">
                {reviewQueue.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="reports" className="gap-2">
            <Flag className="h-4 w-4" />
            Lab Reports
            {labReportStats && labReportStats.open > 0 && (
              <Badge variant="destructive" className="ml-1">
                {labReportStats.open}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Users Tab */}
        <TabsContent value="users" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Users</CardTitle>
                <Users className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats?.totalUsers ?? 0}</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">System Admins</CardTitle>
                <Shield className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats?.adminCount ?? 0}</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Restricted Users</CardTitle>
                <UserX className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats?.restrictedCount ?? 0}</div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>User Management</CardTitle>
              <CardDescription>
                View and manage all registered users.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-4 flex items-center gap-4">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="Search by name or email..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-10"
                  />
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => refetch()}
                  disabled={isLoading}
                >
                  <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>

              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>User</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead className="w-[70px]">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {isLoading ? (
                      <TableRow>
                        <TableCell colSpan={5} className="h-24 text-center">
                          Loading...
                        </TableCell>
                      </TableRow>
                    ) : users?.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={5} className="h-24 text-center">
                          No users found.
                        </TableCell>
                      </TableRow>
                    ) : (
                      users?.map((user) => (
                        <TableRow key={user.id}>
                          <TableCell>
                            <div className="flex items-center gap-3">
                              <Avatar className="h-8 w-8">
                                <AvatarImage src={user.image ?? undefined} />
                                <AvatarFallback>{getInitials(user.name)}</AvatarFallback>
                              </Avatar>
                              <span className="font-medium">{user.name ?? "Unnamed"}</span>
                            </div>
                          </TableCell>
                          <TableCell>{user.email}</TableCell>
                          <TableCell>
                            <div className="flex gap-2">
                              {user.isSystemAdmin && (
                                <Badge variant="default">Admin</Badge>
                              )}
                              {user.isRestricted && (
                                <Badge variant="destructive">Restricted</Badge>
                              )}
                              {!user.isSystemAdmin && !user.isRestricted && (
                                <Badge variant="secondary">User</Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            {formatDistanceToNow(new Date(user.createdAt), { addSuffix: true })}
                          </TableCell>
                          <TableCell>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon">
                                  <MoreHorizontal className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem
                                  onClick={() =>
                                    toggleAdminMutation.mutate({
                                      userId: user.id,
                                      isSystemAdmin: !user.isSystemAdmin,
                                    })
                                  }
                                >
                                  {user.isSystemAdmin ? (
                                    <>
                                      <ShieldOff className="mr-2 h-4 w-4" />
                                      Remove Admin
                                    </>
                                  ) : (
                                    <>
                                      <Shield className="mr-2 h-4 w-4" />
                                      Make Admin
                                    </>
                                  )}
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onClick={() =>
                                    restrictUserMutation.mutate({
                                      userId: user.id,
                                      isRestricted: !user.isRestricted,
                                    })
                                  }
                                  className={user.isRestricted ? "" : "text-destructive"}
                                >
                                  {user.isRestricted ? (
                                    <>
                                      <Users className="mr-2 h-4 w-4" />
                                      Unrestrict User
                                    </>
                                  ) : (
                                    <>
                                      <UserX className="mr-2 h-4 w-4" />
                                      Restrict User
                                    </>
                                  )}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Dockerfile Review Tab */}
        <TabsContent value="review" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Dockerfile Review Queue</CardTitle>
                  <CardDescription>
                    Review and fix failed LLM-generated Dockerfiles
                  </CardDescription>
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => refetchReviews()}
                  disabled={reviewLoading}
                >
                  <RefreshCw className={`h-4 w-4 ${reviewLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {reviewLoading ? (
                <div className="h-24 flex items-center justify-center text-muted-foreground">
                  Loading...
                </div>
              ) : !reviewQueue || reviewQueue.length === 0 ? (
                <div className="h-24 flex flex-col items-center justify-center text-muted-foreground">
                  <FileCode className="h-8 w-8 mb-2 opacity-50" />
                  <p>No pending Dockerfile reviews</p>
                  <p className="text-sm">Failed LLM generations will appear here</p>
                </div>
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>CVE ID</TableHead>
                        <TableHead>Recipe</TableHead>
                        <TableHead>Confidence</TableHead>
                        <TableHead>Attempts</TableHead>
                        <TableHead>Errors</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead className="w-[100px]">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {reviewQueue.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell className="font-mono">{item.cve_id}</TableCell>
                          <TableCell className="max-w-[200px] truncate">
                            {item.recipe_name}
                          </TableCell>
                          <TableCell>
                            {item.confidence_score !== null ? (
                              <Badge
                                variant={
                                  item.confidence_score >= 70
                                    ? "default"
                                    : item.confidence_score >= 50
                                      ? "secondary"
                                      : "destructive"
                                }
                              >
                                {item.confidence_score}%
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell>{item.attempts}</TableCell>
                          <TableCell className="max-w-[200px]">
                            <span className="text-sm text-destructive truncate block">
                              {item.errors[0] || "Unknown error"}
                            </span>
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {item.created_at
                              ? formatDistanceToNow(new Date(item.created_at), { addSuffix: true })
                              : "-"}
                          </TableCell>
                          <TableCell>
                            <Button size="sm" onClick={() => handleReviewClick(item)}>
                              Review
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Lab Reports Tab */}
        <TabsContent value="reports" className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Reports</CardTitle>
                <Flag className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{labReportStats?.total ?? 0}</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Open</CardTitle>
                <AlertCircle className="h-4 w-4 text-destructive" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-destructive">
                  {labReportStats?.open ?? 0}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Investigating</CardTitle>
                <Search className="h-4 w-4 text-yellow-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-yellow-600">
                  {labReportStats?.investigating ?? 0}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Fixed</CardTitle>
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-600">
                  {labReportStats?.fixed ?? 0}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Lab Reports by Recipe</CardTitle>
                  <CardDescription>
                    User-reported issues grouped by recipe for easy triage
                  </CardDescription>
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => refetchReports()}
                  disabled={reportsLoading}
                >
                  <RefreshCw className={`h-4 w-4 ${reportsLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {reportsLoading ? (
                <div className="h-24 flex items-center justify-center text-muted-foreground">
                  Loading...
                </div>
              ) : !labReports || labReports.byRecipe.length === 0 ? (
                <div className="h-24 flex flex-col items-center justify-center text-muted-foreground">
                  <Flag className="h-8 w-8 mb-2 opacity-50" />
                  <p>No lab reports yet</p>
                  <p className="text-sm">User-submitted issues will appear here</p>
                </div>
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Recipe</TableHead>
                        <TableHead>Software</TableHead>
                        <TableHead>Open Reports</TableHead>
                        <TableHead>Total Reports</TableHead>
                        <TableHead className="w-[100px]">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {labReports.byRecipe.map((group) => (
                        <TableRow key={group.recipe.id}>
                          <TableCell className="font-medium">
                            {group.recipe.name}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {group.recipe.software}
                          </TableCell>
                          <TableCell>
                            {group.openCount > 0 ? (
                              <Badge variant="destructive">{group.openCount}</Badge>
                            ) : (
                              <Badge variant="secondary">0</Badge>
                            )}
                          </TableCell>
                          <TableCell>{group.reports.length}</TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              onClick={() => handleReportClick(group.recipe.id)}
                            >
                              View
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
