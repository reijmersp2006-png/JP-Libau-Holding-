"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { API_BASE, useApi } from "@/lib/api";
import { NAV } from "@/lib/nav";

interface Health { status: string; environment: string; holding_data: boolean; live_trading: boolean; kill: boolean }

function Logo() {
  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 28 28" className="h-7 w-7" aria-hidden>
        <rect x="0.5" y="0.5" width="27" height="27" rx="7" fill="#101318" stroke="rgba(255,255,255,.10)" />
        <path d="M8 20V8l12 12V8" fill="none" stroke="#B4DEF8" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-[13px] font-semibold tracking-[0.18em] text-white">NEXUS <span className="text-slate-400">AI</span></div>
        <div className="text-[10.5px] text-slate-500">Trading intelligence</div>
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
          <div className="mb-1.5 px-2.5 text-[10.5px] font-medium uppercase tracking-[0.1em] text-slate-600">{g}</div>
          <ul className="space-y-0.5">
            {NAV.filter((n) => n.group === g).map((n) => {
              const active = path === n.href;
              return (
                <li key={n.href}>
                  <Link href={n.href} onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`group flex items-center justify-between rounded-md px-2.5 py-[7px] text-[13px] transition-colors ${
                      active ? "bg-white/[.06] text-white" : "text-slate-400 hover:bg-white/[.03] hover:text-slate-200"}`}>
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
            {env === "demo" ? "Demo-omgeving" : env === "paper" ? "Paper trading" : "Geen data"}
          </Chip>
          <span className="hidden sm:inline-flex"><Chip tone="slate">Live handelen uit</Chip></span>
          {data.kill ? <Chip tone="rose" pulse>Noodstop actief</Chip> : <Chip tone="emerald">Noodstop paraat</Chip>}
        </>
      )}
    </div>
  );
}

function Chip({ tone, children, pulse }: { tone: string; children: ReactNode; pulse?: boolean }) {
  const t: Record<string, string> = {
    cyan: "text-cyan-300", violet: "text-violet-300", rose: "text-rose-200 border-rose-500/40 bg-rose-500/10",
    emerald: "text-emerald-300", slate: "text-slate-400",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border border-white/[.07] px-2.5 py-1 text-[11.5px] font-medium ${t[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${pulse ? "pulse-dot" : ""}`} />
      {children}
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only z-50 rounded-md bg-graphite-800 px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:left-3 focus:top-3">Naar de inhoud</a>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/[.05] bg-graphite-950 px-3 py-5 lg:flex">
        <div className="mb-8 px-2.5"><Logo /></div>
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
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-white/[.05] bg-void/85 px-4 py-3 backdrop-blur-md md:px-8">
          <div className="flex items-center gap-3">
            <button className="rounded-md border border-slate-700 p-1.5 lg:hidden" aria-label="Menu openen" onClick={() => setOpen(true)}>
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
            </button>
            <div className="hidden sm:block lg:hidden"><Logo /></div>
          </div>
          <StatusBar />
        </header>
        <main id="main" className="mx-auto w-full max-w-[1560px] flex-1 px-4 py-7 md:px-8">{children}</main>
      </div>
    </div>
  );
}
