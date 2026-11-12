"use client";

import type { ReactNode } from "react";
import { useApi } from "@/lib/api";
import type { CommandCenter } from "@/lib/types";
import { EnvBanner } from "./Banner";
import { ErrorBox, Skeleton } from "./ui";

/** Laadt de Command-Center-stand en toont laad- en foutstatus; ``children`` krijgt de data. */
export function WithCC({ children, refreshMs = 30_000 }: { children: (d: CommandCenter, refresh: () => void) => ReactNode; refreshMs?: number }) {
  const { data, error, loading, refresh } = useApi<CommandCenter>("/api/command-center", refreshMs);
  if (loading && !data) return <div className="space-y-3"><Skeleton className="h-8 w-72" /><Skeleton className="h-64" /></div>;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  if (!data) return null;
  return <><EnvBanner env={data.environment} />{children(data, refresh)}</>;
}
