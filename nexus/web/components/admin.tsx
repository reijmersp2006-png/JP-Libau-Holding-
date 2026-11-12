"use client";

import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";

/** Admin-acties: het token blijft alleen in het geheugen van dit tabblad en gaat als Bearer mee. */
export function useAdmin() {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  async function post<T = unknown>(path: string, body?: unknown, done?: (r: T) => void): Promise<T | null> {
    setBusy(path); setMsg(null);
    try {
      const r = await api<T>(path, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: body ? JSON.stringify(body) : undefined });
      setMsg("Klaar");
      done?.(r);
      return r;
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
      return null;
    } finally { setBusy(null); }
  }
  const field = (
    <div className="flex items-center gap-2">
      <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="admin-token"
        aria-label="Admin-token" className="w-40 rounded-md border border-white/[.08] bg-white/[.02] px-2.5 py-1.5 text-[12.5px] text-slate-200 placeholder:text-slate-600 focus:border-white/20" />
      {msg && <span className="max-w-xs truncate text-[12px] text-slate-400" title={msg}>{msg}</span>}
    </div>
  );
  return { token, busy, post, field };
}

export function Btn({ onClick, disabled, children, primary = false }: { onClick: () => void; disabled?: boolean; children: ReactNode; primary?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={`rounded-md px-3 py-1.5 text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${primary
        ? "bg-cyan-300/90 font-medium text-[#07080B] hover:bg-cyan-200" : "border border-white/[.1] text-slate-200 hover:border-white/25"}`}>
      {children}
    </button>
  );
}
