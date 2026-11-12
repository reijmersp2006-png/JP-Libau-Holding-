"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { time } from "@/lib/format";
import { Empty, Skeleton } from "./ui";

interface Stage { stage: string; status: string; at: string | null; ref: string | null; detail: string }
interface Episode { kind: string; id: number; symbol: string; at: string; stages: Stage[] }

const LABEL: Record<string, string> = {
  market_event: "Marktgebeurtenis", intelligence: "Analyse", quant: "Kwantitatief", debate: "Agent-debat",
  risk_review: "Risicotoets", proposal: "Voorstel", execution: "Uitvoering", outcome: "Uitkomst", learning: "Leren",
};
const DONE = new Set(["done", "approved", "filled"]);
function color(s: string) {
  if (DONE.has(s)) return { dot: "#8CCBF2", text: "text-slate-200" };
  if (s === "vetoed" || s === "failed") return { dot: "#E25A64", text: "text-rose-300" };
  if (s === "pending" || s === "escalated") return { dot: "#DDB25C", text: "text-amber-300" };
  return { dot: "transparent", text: "text-slate-600" };
}

/** AI Decision Flow: per episode welke stap echt gebeurde, van nieuws tot leren. Niets wordt ingevuld. */
export function DecisionFlow() {
  const { data, loading, error } = useApi<Episode[]>("/api/central/timeline?limit=12", 30_000);
  const [i, setI] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  if (loading && !data) return <Skeleton className="h-48" />;
  if (error && !data) return <Empty>Tijdlijn niet te laden: {error}</Empty>;
  if (!data?.length) return <Empty>Nog geen besluitketen: er is nog geen Council-run of handelsvoorstel geweest.</Empty>;
  const ep = data[Math.min(i, data.length - 1)];
  const n = ep.stages.length;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {data.slice(0, 8).map((e, k) => (
          <button key={`${e.kind}-${e.id}`} onClick={() => { setI(k); setOpen(null); }} aria-pressed={k === i}
            className={`rounded-md px-2.5 py-1 text-[12px] transition-colors ${k === i ? "bg-white/[.08] text-white" : "text-slate-400 hover:text-slate-200"}`}>
            {e.symbol} <span className="text-slate-500">{e.kind === "council" ? "Council" : "voorstel"} · {time(e.at)}</span>
          </button>
        ))}
      </div>
      <div className="overflow-x-auto pb-1">
        <svg viewBox={`0 0 ${n * 100} 74`} className="min-w-[720px] w-full" role="list" aria-label="Stappen van dit besluit">
          {ep.stages.slice(0, -1).map((s, k) => {
            const both = DONE.has(s.status) && DONE.has(ep.stages[k + 1].status);
            return <line key={k} x1={k * 100 + 58} y1="22" x2={k * 100 + 142} y2="22" stroke={both ? "rgba(140,203,242,.6)" : "rgba(255,255,255,.08)"}
              strokeWidth="1.2" className={both ? "flow" : ""} />;
          })}
          {ep.stages.map((s, k) => {
            const c = color(s.status);
            return (
              <g key={s.stage} role="listitem" tabIndex={0} className="cursor-pointer outline-none"
                onClick={() => setOpen(open === s.stage ? null : s.stage)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setOpen(open === s.stage ? null : s.stage))}
                aria-label={`${LABEL[s.stage]}: ${s.status}`}>
                <circle cx={k * 100 + 50} cy="22" r={open === s.stage ? 9 : 7} fill={c.dot === "transparent" ? "#0B0D11" : c.dot}
                  fillOpacity={c.dot === "transparent" ? 1 : 0.9} stroke={c.dot === "transparent" ? "rgba(255,255,255,.2)" : c.dot} />
                <text x={k * 100 + 50} y="50" textAnchor="middle" className="fill-slate-300 text-[10.5px]">{LABEL[s.stage]}</text>
                <text x={k * 100 + 50} y="64" textAnchor="middle" className="fill-slate-500 text-[9px]">{s.status === "none" ? "—" : s.status}</text>
              </g>
            );
          })}
        </svg>
      </div>
      {open && (() => {
        const s = ep.stages.find((x) => x.stage === open)!;
        return (
          <div className="fade-up mt-3 rounded-lg border border-white/[.06] bg-white/[.02] p-3 text-[12.5px]">
            <div className="font-medium text-slate-100">{LABEL[s.stage]} · <span className={color(s.status).text}>{s.status}</span></div>
            <div className="mt-1 text-slate-400">{s.detail || "Geen details."}</div>
            <div className="mt-1 font-mono text-[11px] text-slate-500">{s.ref ?? "geen verwijzing"}{s.at ? ` · ${time(s.at)}` : ""}</div>
          </div>
        );
      })()}
    </div>
  );
}
