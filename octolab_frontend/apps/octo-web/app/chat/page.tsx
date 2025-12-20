"use client";

import { useState } from "react";
import { Shield, Terminal, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ChatbotPanel } from "@/components/chat/chatbot-panel";
import { ChatHistory } from "@/components/chat/chat-history";
import { api } from "@/lib/trpc/react";

export default function ChatPage() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const utils = api.useUtils();

  const handleNewChat = () => {
    setSelectedSessionId(null);
  };

  const handleSessionCreated = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    utils.chat.listSessions.invalidate();
  };

  const handleSelectSession = (sessionId: string | null) => {
    setSelectedSessionId(sessionId);
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Top Bar - Breadcrumb Style */}
      <div className="border-b bg-card/50 px-6 py-3">
        <div className="mx-auto max-w-7xl flex flex-wrap items-center justify-between gap-4">
          {/* Left: Platform info breadcrumb */}
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Shield className="h-4 w-4 text-orange-500" />
              <span>CVE Rehearsal Platform</span>
            </div>
            <span className="text-muted-foreground/50">•</span>
            <div className="flex items-center gap-1.5">
              <Terminal className="h-4 w-4" />
              <span>Isolated Lab Environments</span>
            </div>
            <span className="text-muted-foreground/50">•</span>
            <div className="flex items-center gap-1.5">
              <Zap className="h-4 w-4" />
              <span>Instant Deployment</span>
            </div>
          </div>

          {/* Right: Tags */}
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="rounded-full text-xs px-2.5 py-0.5 border-muted-foreground/20">
              Penetration Testing
            </Badge>
            <Badge variant="outline" className="rounded-full text-xs px-2.5 py-0.5 border-muted-foreground/20">
              Red Team
            </Badge>
            <Badge variant="outline" className="rounded-full text-xs px-2.5 py-0.5 border-muted-foreground/20">
              Security Research
            </Badge>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="mx-auto max-w-7xl p-6">
        <div className="grid gap-6 lg:grid-cols-[280px,1fr,320px]">
          {/* Chat History - Left Sidebar */}
          <div className="hidden lg:block h-[calc(100vh-140px)] min-h-[600px]">
            <ChatHistory
              selectedSessionId={selectedSessionId}
              onSelectSession={handleSelectSession}
              onNewChat={handleNewChat}
            />
          </div>

          {/* Chatbot Panel - Main */}
          <div className="h-[calc(100vh-140px)] min-h-[600px]">
            <ChatbotPanel
              sessionId={selectedSessionId}
              onSessionCreated={handleSessionCreated}
            />
          </div>

          {/* Info Panel - Right Sidebar */}
          <div className="hidden lg:block space-y-4">
            {/* Quick Start */}
            <div className="rounded-xl border bg-card p-4">
              <h2 className="text-base font-semibold">Quick Start</h2>
              <div className="mt-3 space-y-3">
                <div className="flex items-start gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-md bg-orange-100 text-orange-600 font-semibold text-xs">
                    1
                  </div>
                  <div>
                    <h3 className="font-medium text-xs">Describe Your Scenario</h3>
                    <p className="text-xs text-muted-foreground">CVE, software, or attack type</p>
                  </div>
                </div>

                <div className="flex items-start gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-md bg-orange-100 text-orange-600 font-semibold text-xs">
                    2
                  </div>
                  <div>
                    <h3 className="font-medium text-xs">Review the Recipe</h3>
                    <p className="text-xs text-muted-foreground">AI generates lab config</p>
                  </div>
                </div>

                <div className="flex items-start gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-md bg-orange-100 text-orange-600 font-semibold text-xs">
                    3
                  </div>
                  <div>
                    <h3 className="font-medium text-xs">Deploy & Practice</h3>
                    <p className="text-xs text-muted-foreground">Spin up isolated containers</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Popular Labs */}
            <div className="rounded-xl border bg-card p-4">
              <h2 className="text-base font-semibold">Popular Labs</h2>
              <div className="mt-3 space-y-2">
                {[
                  { name: "Apache Path Traversal", cve: "CVE-2021-41773", difficulty: "Medium" },
                  { name: "Log4Shell RCE", cve: "CVE-2021-44228", difficulty: "Hard" },
                  { name: "SQL Injection", cve: "Various", difficulty: "Easy" },
                  { name: "Java Deserialization", cve: "Various", difficulty: "Hard" },
                ].map((lab) => (
                  <div
                    key={lab.name}
                    className="flex items-center justify-between rounded-lg border p-2 hover:bg-muted/50 cursor-pointer transition-colors"
                  >
                    <div>
                      <p className="text-xs font-medium">{lab.name}</p>
                      <p className="text-[10px] text-muted-foreground">{lab.cve}</p>
                    </div>
                    <Badge
                      variant="outline"
                      className={`text-[10px] px-1.5 py-0 ${
                        lab.difficulty === "Easy"
                          ? "border-green-200 bg-green-50 text-green-700"
                          : lab.difficulty === "Medium"
                          ? "border-yellow-200 bg-yellow-50 text-yellow-700"
                          : "border-red-200 bg-red-50 text-red-700"
                      }`}
                    >
                      {lab.difficulty}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
