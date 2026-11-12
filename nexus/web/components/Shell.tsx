"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { API_BASE, useApi } from "@/lib/api";
import { NAV } from "@/lib/nav";

interface Health { status: string; environment: string; holding_data: boolean; live_trading: boolean; kill: boolean }

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative grid h-8 w-8 place-items-center rounded-lg border border-cyan-400/40 bg-cyan-400/10 shadow-[0_0_24px_-6px_rgba(86,223,245,.7)]">
        <svg viewBox="0 0 24 24" className="h-4 w-4 text-cyan-300" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 20V4l16 16V4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-[0.2em] text-white">NEXUS<span className="text-cyan-300"> AI</span></div>
        <div className="text-[10px] text-slate-500">Intelligence Behind Every Trade.</div>
      </div>
    </div>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const groups = [...new Set(NAV.map((n) => n.group))];
  return (
    <nav aria-label="Hoofdmenu" className="space-y-5">
      {groups.map((g) => (
        <div key={g}>
          <div className="eyebrow mb-1.5 px-2">{g}</div>
          <ul className="space-y-0.5">
            {NAV.filter((n) => n.group === g).map((n) => {
              const active = path === n.href;
              return (
                <li key={n.href}>
                  <Link href={n.href} onClick={onNavigate}
                    className={`group flex items-center justify-between rounded-lg px-2 py-1.5 text-[13px] transition-colors ${
                      active ? "bg-cyan-400/10 text-cyan-200 shadow-[inset_2px_0_0_#56DFF5]" : "text-slate-400 hover:bg-white/[.03] hover:text-slate-200"}`}>
                    <span>{n.label}</span>
                    {!n.ready && <span className="font-mono text-[9px] text-slate-600 group-hover:text-slate-500">F{n.phase}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function StatusBar() {
  const { data, error, refresh } = useApi<Health>("/api/health", 15_000);
  const [live, setLive] = useState(false);
  useEffect(() => {
    window.addEventListener("nexus:controls", refresh);
    return () => window.removeEventListener("nexus:controls", refresh);
  }, [refresh]);
  useEffect(() => {
    // Realtime: noodstop- en modusgebeurtenissen direct tonen; valt terug op elke 15 s verversen.
    let ws: WebSocket | null = null, stop = false, retry: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      ws = new WebSocket(API_BASE.replace(/^http/, "ws") + "/ws/events");
      ws.onopen = () => setLive(true);
      ws.onclose = () => { setLive(false); if (!stop) retry = setTimeout(connect, 10_000); };
      ws.onmessage = (m) => {
        const kind = JSON.parse(m.data).kind;
        if (kind === "kill" || kind === "mode") refresh();
        window.dispatchEvent(new CustomEvent("nexus:event", { detail: kind }));
      };
    };
    connect();
    return () => { stop = true; clearTimeout(retry); ws?.close(); };
  }, [refresh]);
  const env = data?.environment;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {error && <Chip tone="rose">API offline</Chip>}
      {data && <span title={live ? "realtime verbinding actief" : "geen realtime verbinding; verversen elke 15 s"}
        className={`hidden h-2 w-2 rounded-full sm:inline-block ${live ? "pulse-dot bg-emerald-400" : "bg-slate-600"}`} />}
      {data && (
        <>
          <Chip tone={env === "demo" ? "violet" : env === "paper" ? "cyan" : "slate"}>
            {env === "demo" ? "DEMO-OMGEVING" : env === "paper" ? "PAPER TRADING" : "GEEN DATA"}
          </Chip>
          <span className="hidden sm:inline-flex"><Chip tone="slate">Live handelen: UIT</Chip></span>
          {data.kill ? <Chip tone="rose" pulse>NOODSTOP ACTIEF</Chip> : <Chip tone="emerald">Noodstop paraat</Chip>}
        </>
      )}
    </div>
  );
}

function Chip({ tone, children, pulse }: { tone: string; children: ReactNode; pulse?: boolean }) {
  const t: Record<string, string> = {
    cyan: "border-cyan-400/30 text-cyan-200 bg-cyan-400/5", violet: "border-violet-400/40 text-violet-200 bg-violet-400/10",
    rose: "border-rose-500/50 text-rose-200 bg-rose-500/15", emerald: "border-emerald-400/30 text-emerald-200 bg-emerald-400/5",
    slate: "border-slate-600/50 text-slate-300 bg-slate-500/5",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium tracking-wide ${t[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${pulse ? "pulse-dot" : ""}`} />
      {children}
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/5 bg-graphite-950/70 px-3 py-4 backdrop-blur lg:flex">
        <div className="mb-6 px-2"><Logo /></div>
        <div className="flex-1 overflow-y-auto pr-1"><Nav /></div>
        <p className="mt-4 px-2 text-[10.5px] leading-relaxed text-slate-600">
          Winst is niet gegarandeerd. Alle cijfers dragen een herkomstlabel; zonder data tonen we niets.
        </p>
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 bg-black/70 lg:hidden" onClick={() => setOpen(false)}>
          <div className="h-full w-72 overflow-y-auto border-r border-white/10 bg-graphite-950 p-4" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6"><Logo /></div>
            <Nav onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-white/5 bg-void/80 px-4 py-3 backdrop-blur md:px-6">
          <div className="flex items-center gap-3">
            <button className="rounded-md border border-slate-700 p-1.5 lg:hidden" aria-label="Menu openen" onClick={() => setOpen(true)}>
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
            </button>
            <div className="hidden sm:block lg:hidden"><Logo /></div>
          </div>
          <StatusBar />
        </header>
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 md:px-6">{children}</main>
      </div>
    </div>
  );
}
