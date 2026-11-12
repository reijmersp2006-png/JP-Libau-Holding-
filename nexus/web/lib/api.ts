"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// De API-sleutels blijven op de server. De frontend kent alleen het adres van de NEXUS API.
export const API_BASE = process.env.NEXT_PUBLIC_NEXUS_API ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) { super(message); }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init, cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, `NEXUS API niet bereikbaar op ${API_BASE}`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : d?.error ?? `fout ${res.status}`;
    throw new ApiError(res.status, msg, d);
  }
  return body as T;
}

export function useApi<T>(path: string, refreshMs = 30_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await api<T>(path);
      if (!alive.current) return;
      setData(d); setError(null); setUpdatedAt(new Date());
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    const first = setTimeout(load, 0);          // eerste keer direct, daarna elke refreshMs
    const t = setInterval(load, refreshMs);
    return () => { alive.current = false; clearTimeout(first); clearInterval(t); };
  }, [load, refreshMs]);

  return { data, error, loading, updatedAt, refresh: load };
}
