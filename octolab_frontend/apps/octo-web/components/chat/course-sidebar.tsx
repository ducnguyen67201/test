"use client";

import { useState } from "react";
import { Play, Check, Lock, FileText, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface Lesson {
  id: string;
  title: string;
  duration: string;
  completed: boolean;
  active?: boolean;
  locked?: boolean;
  type?: "video" | "test";
}

interface Module {
  id: string;
  title: string;
  lessons: Lesson[];
}

const modules: Module[] = [
  {
    id: "1",
    title: "Module 1: Get Started with Figma Basics",
    lessons: [
      { id: "1-1", title: "Introduction to Figma", duration: "02:15:24", completed: true, type: "video" },
      { id: "1-2", title: "Utilizing Figma's Powerful Features", duration: "02:15:24", completed: true, type: "video" },
      { id: "1-3", title: "Mastering Autolayout", duration: "02:15:24", completed: false, active: true, type: "video" },
      { id: "1-4", title: "Topical examination", duration: "02:15:24", completed: false, locked: true, type: "test" },
    ],
  },
  {
    id: "2",
    title: "Module 2: Figma components",
    lessons: [],
  },
  {
    id: "3",
    title: "Module 3: Create your own design system",
    lessons: [],
  },
];

export function CourseSidebar() {
  const [expandedModules, setExpandedModules] = useState<string[]>(["1"]);

  const toggleModule = (moduleId: string) => {
    setExpandedModules((prev) =>
      prev.includes(moduleId)
        ? prev.filter((id) => id !== moduleId)
        : [...prev, moduleId]
    );
  };

  const completedCount = modules.reduce(
    (acc, m) => acc + m.lessons.filter((l) => l.completed).length,
    0
  );
  const totalCount = modules.reduce((acc, m) => acc + m.lessons.length, 0);

  return (
    <div className="rounded-xl border bg-card p-6">
      {/* Course Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-orange-100">
          <Play className="h-5 w-5 fill-orange-500 text-orange-500" />
        </div>
        <div className="flex-1">
          <h2 className="font-semibold">Mastering Figma in 7 days unleashed</h2>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="text-orange-500">✦</span>
              {completedCount}/{totalCount} completed
            </span>
          </div>
        </div>
      </div>

      {/* Modules */}
      <div className="mt-6 space-y-2">
        {modules.map((module) => {
          const isExpanded = expandedModules.includes(module.id);
          const hasLessons = module.lessons.length > 0;

          return (
            <div key={module.id}>
              {/* Module Header */}
              <button
                onClick={() => hasLessons && toggleModule(module.id)}
                className={cn(
                  "flex w-full items-center justify-between rounded-lg px-4 py-3 text-left transition-colors",
                  isExpanded && hasLessons
                    ? "bg-orange-50 text-orange-600"
                    : "hover:bg-muted"
                )}
              >
                <span className={cn("text-sm font-medium", isExpanded && hasLessons && "text-orange-600")}>
                  {module.title}
                </span>
                {hasLessons ? (
                  isExpanded ? (
                    <ChevronUp className="h-4 w-4" />
                  ) : (
                    <ChevronDown className="h-4 w-4" />
                  )
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>

              {/* Lessons */}
              {isExpanded && hasLessons && (
                <div className="mt-2 space-y-1 pl-2">
                  {module.lessons.map((lesson) => (
                    <div
                      key={lesson.id}
                      className={cn(
                        "flex items-center gap-3 rounded-lg p-3 transition-colors",
                        lesson.active && "border-l-2 border-orange-500 bg-orange-50/50"
                      )}
                    >
                      {/* Icon */}
                      <div
                        className={cn(
                          "flex h-10 w-10 items-center justify-center rounded-full",
                          lesson.type === "test"
                            ? "bg-orange-100"
                            : "border-2 border-muted-foreground/20 bg-background"
                        )}
                      >
                        {lesson.type === "test" ? (
                          <div className="relative">
                            <span className="absolute -top-3 -right-2 rounded bg-orange-500 px-1 text-[10px] font-medium text-white">
                              TEST
                            </span>
                            <FileText className="h-4 w-4 text-orange-500" />
                          </div>
                        ) : (
                          <Play className="h-4 w-4 text-muted-foreground" />
                        )}
                      </div>

                      {/* Content */}
                      <div className="flex-1">
                        <p className="text-sm font-medium">{lesson.title}</p>
                        <p className="flex items-center gap-1 text-xs text-muted-foreground">
                          <span>◷</span> {lesson.duration}
                        </p>
                      </div>

                      {/* Status */}
                      <div>
                        {lesson.completed ? (
                          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-orange-500">
                            <Check className="h-3 w-3 text-white" />
                          </div>
                        ) : lesson.locked ? (
                          <Lock className="h-4 w-4 text-muted-foreground" />
                        ) : lesson.active ? (
                          <span className="text-orange-500">✦</span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
