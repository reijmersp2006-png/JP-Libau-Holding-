"use client";

import { safeUrl } from "@/lib/url";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { eur, time } from "@/lib/format";
import { Empty, Skeleton } from "./ui";

export interface Briefing {
  day: string; generated_at: string; draft?: boolean;
  portfolio?: { equity_eur: number; pnl_eur: number; positions: number };
  news: { id: number; title: string; source: string; category: string; relevance: number | null; url: string }[];
  trading: { proposals: number; vetoes: number; fills: number; live_trading: boolean };
  research?: { symbol: string; champion_sharpe: number; buy_hold_sharpe: number; passed_dev_gates: string[]; holdout: string };
  learning: { hypotheses_resolved_7d: number; supported: string[]; decisions_measured: number };
  ai: { council_runs: number; done: number; cost_usd: number; unavailable: number };
  actions: { task?: number; kind: string; text: string }[]; missing: string[];
}

export function BriefingCard({ full = false }: { full?: boolean }) {
  const { data, loading, error } = useApi<Briefing>("/api/central/briefing", 120_000);
  if (loading && !data) return <Skeleton className="h-48" />;
  if (error && !data) return <Empty>Briefing niet te laden: {error}</Empty>;
  if (!data) return null;
  const b = data;
  return (
    <div className="space-y-4 text-[13px]">
      <div className="flex items-baseline justify-between">
        <span className="text-slate-400">{b.draft ? "Concept, nog niet vastgelegd" : "Vastgelegd"} · {time(b.generated_at)}</span>
        {!full && <Link href="/hq" className="text-[12px] text-cyan-300 hover:text-cyan-200">Volledige briefing</Link>}
      </div>
      <div>
        <div className="eyebrow mb-1.5">Aanbevolen acties</div>
        {b.actions.length ? (
          <ol className="space-y-1.5">
            {b.actions.slice(0, full ? 20 : 4).map((a, i) => (
              <li key={i} className="flex gap-2.5"><span className="num mt-px text-slate-600">{i + 1}</span><span className="text-slate-200">{a.text}</span></li>
            ))}
          </ol>
        ) : <div className="text-slate-500">Geen acties nodig.</div>}
      </div>
      {full && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div><div className="eyebrow mb-1">Portefeuille (paper)</div>{b.portfolio ? <div className="num text-slate-200">{eur(b.portfolio.equity_eur)} · resultaat {eur(b.portfolio.pnl_eur)} · {b.portfolio.positions} posities</div> : <div className="text-slate-500">niet beschikbaar</div>}</div>
          <div><div className="eyebrow mb-1">Handel (24 uur)</div><div className="text-slate-200">{b.trading.proposals} voorstellen · {b.trading.vetoes} veto&apos;s · {b.trading.fills} vullingen · live uit</div></div>
          <div><div className="eyebrow mb-1">Onderzoek</div>{b.research ? <div className="text-slate-200">{b.research.symbol}: kampioen Sharpe {b.research.champion_sharpe?.toFixed(2)} tegen koop-en-houd {b.research.buy_hold_sharpe?.toFixed(2)} · holdout {b.research.holdout === "contaminated" ? "besmet, wacht op nieuwe data" : b.research.holdout}</div> : <div className="text-slate-500">nog geen arena-run</div>}</div>
          <div><div className="eyebrow mb-1">Leren (7 dagen)</div><div className="text-slate-200">{b.learning.hypotheses_resolved_7d} hypothesen getoetst · {b.learning.decisions_measured} besluiten afgerekend</div></div>
          <div><div className="eyebrow mb-1">AI (24 uur)</div><div className="text-slate-200">{b.ai.council_runs} Council-runs, {b.ai.done} voltooid · ${b.ai.cost_usd.toFixed(2)}</div></div>
          <div><div className="eyebrow mb-1">Belangrijk nieuws</div>{b.news.length ? <ul className="space-y-1">{b.news.map((n) => <li key={n.id}><a href={safeUrl(n.url)} target="_blank" rel="noreferrer noopener" className="text-slate-200 hover:text-white">{n.title}</a> <span className="text-slate-500">{n.source}</span></li>)}</ul> : <div className="text-slate-500">geen</div>}</div>
        </div>
      )}
      {b.missing.length > 0 && (
        <div>
          <div className="eyebrow mb-1">Ontbreekt of onzeker</div>
          <ul className="space-y-0.5 text-slate-500">{b.missing.map((m) => <li key={m}>· {m}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
