"use client";

import { useState } from "react";
import { BacktestView } from "@/components/BacktestView";
import { ErrorBox, PageTitle, Panel, Skeleton } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { BacktestResult, RunSummary, StrategySpec } from "@/lib/types";

interface Resp { strategies: StrategySpec[]; symbols: string[]; runs: RunSummary[] }

export default function Page() {
  const { data, error, loading, refresh } = useApi<Resp>("/api/strategies", 60_000);
  const [sel, setSel] = useState("trend_sma");
  const [sym, setSym] = useState("BTC-EUR");
  const [spread, setSpread] = useState(0.1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<BacktestResult | null>(null);

  async function run() {
    setBusy(true); setErr(null);
    try {
      const r = await api<BacktestResult>("/api/backtests", { method: "POST", body: JSON.stringify({ strategy: sel, symbol: sym, spread_pct: spread / 100 }) });
      setRes(r); refresh();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  if (loading && !data) return <Skeleton className="h-96" />;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  const specs = data!.strategies;
  const cur = specs.find((s) => s.key === sel);
  return (
    <>
      <PageTitle title="Strategy Lab" sub="Geversioneerde, deterministische strategieën. Parameters liggen per versie vast; er wordt niet geoptimaliseerd op de data waarop we beoordelen. Geen enkele strategie wordt als winstgevend aangenomen." />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="grid gap-3 md:grid-cols-2">
          {specs.map((s) => (
            <button key={s.key} onClick={() => setSel(s.key)}
              className={`panel p-4 text-left transition ${sel === s.key ? "panel-glow" : "opacity-80 hover:opacity-100"}`}>
              <div className="flex items-center justify-between"><span className="font-semibold text-slate-100">{s.name}</span>
                <span className="font-mono text-[11px] text-slate-500">v{s.version} · {s.status}</span></div>
              <div className="mt-1 font-mono text-[11px] text-cyan-300/80">{Object.entries(s.params).map(([k, v]) => `${k}=${v}`).join(", ")}</div>
              <dl className="mt-2 grid grid-cols-[64px_1fr] gap-x-2 gap-y-1 text-xs">
                <dt className="text-slate-500">Instap</dt><dd className="text-slate-300">{s.entry}</dd>
                <dt className="text-slate-500">Uitstap</dt><dd className="text-slate-300">{s.exit}</dd>
                <dt className="text-slate-500">Data</dt><dd className="text-slate-400">{s.required_data}</dd>
                <dt className="text-slate-500">Risico</dt><dd className="text-slate-400">{s.risk}</dd>
              </dl>
            </button>
          ))}
        </div>
        <Panel title="Backtest starten" glow>
          <div className="space-y-3 text-sm">
            <div><div className="eyebrow mb-1">Strategie</div><div className="text-slate-100">{cur?.name} v{cur?.version}</div></div>
            <label className="block"><span className="eyebrow mb-1 block">Instrument</span>
              <select value={sym} onChange={(e) => setSym(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-black/40 px-3 py-2">
                {data!.symbols.map((s) => <option key={s}>{s}</option>)}
              </select></label>
            <label className="block"><span className="eyebrow mb-1 block">Spread (%)</span>
              <input type="number" min={0} max={5} step={0.05} value={spread} onChange={(e) => setSpread(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-700 bg-black/40 px-3 py-2 font-mono" /></label>
            <p className="text-xs text-slate-500">Dagkoersen uit de koersdatabase van de holding. 70% in-sample, 30% out-of-sample, 5 vakken, kosten en slippage per afdeling.</p>
            <button onClick={run} disabled={busy} className="w-full rounded-lg bg-cyan-400 px-3 py-2 font-semibold text-void transition hover:bg-cyan-300 disabled:opacity-60">
              {busy ? "Bezig…" : "Backtest draaien"}</button>
            {err && <p role="alert" className="text-xs text-rose-300">{err}</p>}
          </div>
        </Panel>
      </div>
      <div className="mt-4">{res ? <BacktestView r={res} /> : (
        <Panel><p className="text-sm text-slate-500">Kies een strategie en een instrument en draai een backtest. Eerdere runs staan in de Backtesting Studio.</p></Panel>
      )}</div>
    </>
  );
}
