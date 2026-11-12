"use client";

import { useState } from "react";
import { BacktestView } from "@/components/BacktestView";
import { DataBadge, Empty, ErrorBox, PageTitle, Panel, Skeleton } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, num, pct, tone } from "@/lib/format";
import type { BacktestResult, RunSummary } from "@/lib/types";

export default function Page() {
  const { data, error, loading, refresh } = useApi<{ runs: RunSummary[] }>("/api/strategies", 60_000);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function open(id: number) {
    setErr(null);
    try { setRes(await api<BacktestResult>(`/api/backtests/${id}`)); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  if (loading && !data) return <Skeleton className="h-96" />;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  const runs = data!.runs;
  return (
    <>
      <PageTitle title="Backtesting Studio" sub="Alle backtests naast elkaar, out-of-sample tegenover koop-en-houd over dezelfde periode. Een strategie gaat pas naar paper als ze de toets haalt; één goede backtest is nooit genoeg." />
      <Panel title={`Runs (${runs.length})`}>
        {runs.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Wanneer</th><th className="pb-2">Strategie</th><th className="pb-2">Instrument</th><th className="pb-2">Data</th>
                <th className="pb-2 text-right">OOS rendement</th><th className="pb-2 text-right">OOS Sharpe</th><th className="pb-2 text-right">Koop-en-houd</th><th className="pb-2 text-right">Trades</th><th className="pb-2 pl-3">Oordeel</th></tr></thead>
              <tbody>{runs.map((r) => (
                <tr key={r.id} onClick={() => open(r.id)} className="cursor-pointer border-t border-white/[.04] hover:bg-white/[.03]">
                  <td className="py-2 text-slate-400">{ago(r.created_at)}</td><td className="py-2">{r.strategy} <span className="text-slate-500">v{r.version}</span></td>
                  <td className="py-2">{r.symbol}</td><td className="py-2"><DataBadge label={r.data_label} /></td>
                  <td className={`num py-2 text-right ${tone(r.oos.net_return)}`}>{pct(r.oos.net_return, 1, true)}</td>
                  <td className="num py-2 text-right">{num(r.oos.sharpe, 2)}</td>
                  <td className={`num py-2 text-right ${tone(r.benchmark_oos.net_return)}`}>{pct(r.benchmark_oos.net_return, 1, true)} <span className="text-slate-500">({num(r.benchmark_oos.sharpe, 2)})</span></td>
                  <td className="num py-2 text-right">{r.oos.trades ?? "—"}</td>
                  <td className="py-2 pl-3"><span className={r.passes ? "text-emerald-300" : "text-amber-300"}>{r.passes ? "voldoet" : "afgewezen"}</span></td>
                </tr>))}</tbody>
            </table>
          </div>
        ) : <Empty>Nog geen backtests. Start er een in het Strategy Lab.</Empty>}
      </Panel>
      {err && <p className="mt-2 text-sm text-rose-300">{err}</p>}
      {res && <div className="mt-4"><BacktestView r={res} /></div>}
    </>
  );
}
