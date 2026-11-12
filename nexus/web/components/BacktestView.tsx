"use client";

import { ColorType, LineSeries, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { eur, num, pct, tone } from "@/lib/format";
import type { BacktestResult, Metrics } from "@/lib/types";
import { DataBadge, Panel } from "./ui";

function CompareChart({ a, b }: { a: [string, number][]; b: [string, number][] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || a.length < 2) return;
    const chart = createChart(ref.current, {
      height: 260, autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#91A0B8", fontSize: 11 },
      grid: { vertLines: { color: "rgba(145,160,184,.05)" }, horzLines: { color: "rgba(145,160,184,.07)" } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
      localization: { locale: "nl-NL" },
    });
    const toPts = (xs: [string, number][]) => {
      const seen = new Set<number>();
      return xs.map(([t, v]) => ({ time: Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp, value: v }))
        .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)));
    };
    chart.addSeries(LineSeries, { color: "#56DFF5", lineWidth: 2, priceLineVisible: false, title: "strategie" }).setData(toPts(a));
    chart.addSeries(LineSeries, { color: "#9775FA", lineWidth: 1, priceLineVisible: false, title: "koop-en-houd" }).setData(toPts(b));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [a, b]);
  return <div ref={ref} className="h-[260px] w-full" />;
}

const ROWS: [keyof Metrics, string, (v: number | null | undefined) => string][] = [
  ["net_return", "Netto rendement", (v) => pct(v, 1, true)],
  ["annual_return", "Per jaar", (v) => pct(v, 1, true)],
  ["max_drawdown", "Max. daling", (v) => pct(v == null ? v : -v, 1)],
  ["sharpe", "Sharpe", (v) => num(v, 2)],
  ["sortino", "Sortino", (v) => num(v, 2)],
  ["win_rate", "Win rate", (v) => pct(v, 0)],
  ["profit_factor", "Profit factor", (v) => num(v, 2)],
  ["expectancy_eur", "Verwachting / trade", (v) => eur(v)],
  ["exposure", "In de markt", (v) => pct(v, 0)],
  ["costs_eur", "Kosten (incl. spread)", (v) => eur(v)],
];

export function BacktestView({ r }: { r: BacktestResult }) {
  const cols: [string, Metrics][] = [["Hele periode", r.full], ["In-sample", r.in_sample], ["Out-of-sample", r.out_of_sample], ["Koop-en-houd (OOS)", r.benchmark.out_of_sample]];
  const ci = r.out_of_sample.sharpe_ci95;
  return (
    <div className="space-y-4">
      <div className={`rounded-xl border px-4 py-3 text-sm ${r.passes ? "border-emerald-400/40 bg-emerald-400/10" : "border-amber-400/40 bg-amber-400/10"}`}>
        <div className="flex flex-wrap items-center gap-2 font-medium">
          {r.passes ? "Voldoet aan de minimale toets" : "Niet geschikt voor paper of live"}
          <DataBadge label={r.data_label} />
          <span className="text-xs text-slate-400">{r.strategy.name} v{r.strategy.version} · {r.symbol} · {r.data.bars} dagkoersen {r.data.first.slice(0, 10)} t/m {r.data.last.slice(0, 10)}</span>
        </div>
        <ul className="mt-1 list-disc pl-5 text-xs text-slate-300">{r.verdict.map((v) => <li key={v}>{v}</li>)}</ul>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <Panel title="Vermogen: strategie tegen koop-en-houd" label={r.data_label}
          action={<span className="text-[11px] text-slate-500">out-of-sample vanaf {r.data.oos_start.slice(0, 10)}</span>}>
          <CompareChart a={r.equity} b={r.benchmark_equity} />
        </Panel>
        <Panel title="Kerncijfers">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="pb-1.5 font-medium" />{cols.map(([n]) => <th key={n} className="pb-1.5 text-right font-medium">{n}</th>)}</tr></thead>
            <tbody>
              {ROWS.map(([k, label, f]) => (
                <tr key={k} className="border-t border-white/[.04]"><td className="py-1 text-slate-400">{label}</td>
                  {cols.map(([n, m]) => <td key={n} className={`num py-1 text-right ${k === "net_return" ? tone(m[k] as number) : ""}`}>{f(m[k] as number | null)}</td>)}</tr>
              ))}
              <tr className="border-t border-white/[.04]"><td className="py-1 text-slate-400">Trades</td>{cols.map(([n, m]) => <td key={n} className="num py-1 text-right">{m.trades ?? "—"}</td>)}</tr>
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-slate-500">
            95%-interval Sharpe out-of-sample: {ci ? `${num(ci[0], 2)} tot ${num(ci[1], 2)}` : "—"}. Verschil met koop-en-houd (hele periode): <span className={tone(r.benchmark_relative_return)}>{pct(r.benchmark_relative_return, 1, true)}</span>.
          </p>
        </Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Stabiliteit per vak (walk-forward, vaste parameters)">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="pb-1.5 font-medium">Periode</th><th className="pb-1.5 text-right font-medium">Rendement</th><th className="pb-1.5 text-right font-medium">Sharpe</th><th className="pb-1.5 text-right font-medium">Max. daling</th><th className="pb-1.5 text-right font-medium">Koop-en-houd</th></tr></thead>
            <tbody>{r.folds.map((f) => (
              <tr key={f.start} className="border-t border-white/[.04]"><td className="py-1 text-slate-400">{f.start} – {f.end}</td>
                <td className={`num py-1 text-right ${tone(f.net_return)}`}>{pct(f.net_return, 1, true)}</td><td className="num py-1 text-right">{num(f.sharpe, 2)}</td>
                <td className="num py-1 text-right">{pct(-f.max_drawdown, 1)}</td><td className={`num py-1 text-right ${tone(f.benchmark_return)}`}>{pct(f.benchmark_return, 1, true)}</td></tr>
            ))}</tbody>
          </table>
        </Panel>
        <Panel title="Per marktregime (200-dagengemiddelde)">
          {Object.keys(r.regimes).length ? (
            <table className="w-full text-xs"><tbody>
              {Object.entries(r.regimes).map(([k, g]) => (
                <tr key={k} className="border-t border-white/[.04] first:border-0"><td className="py-1.5 text-slate-300">{k === "bull" ? "Stijgende markt" : "Dalende markt"} <span className="text-slate-500">({g.periods} dagen)</span></td>
                  <td className="num py-1.5 text-right">gem. {pct(g.mean_return, 3, true)}/dag</td><td className="num py-1.5 text-right text-slate-500">koop-en-houd {pct(g.benchmark_mean_return, 3, true)}</td><td className="num py-1.5 text-right">Sharpe {num(g.sharpe, 2)}</td></tr>
              ))}
            </tbody></table>
          ) : <p className="text-sm text-slate-500">Te weinig data voor een regime-indeling.</p>}
          <div className="mt-3 text-[11px] leading-relaxed text-slate-500">
            Aannames: kosten {pct(r.assumptions.fee_pct, 2)} (min. {eur(r.assumptions.min_fee_eur)}), slippage {pct(r.assumptions.slippage_pct, 2)}, spread {pct(r.assumptions.spread_pct, 2)}, order max. 1% van de dagomzet. {r.assumptions.execution}.
            Niet gemodelleerd: {r.assumptions.not_modeled.join(", ")}.
          </div>
        </Panel>
      </div>
      <Panel title={`Laatste trades (${r.trades.length})`}>
        {r.trades.length ? (
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-slate-500"><th className="pb-1.5 font-medium">Instap</th><th className="pb-1.5 font-medium">Uitstap</th><th className="pb-1.5 text-right font-medium">Dagen</th><th className="pb-1.5 text-right font-medium">Rendement</th><th className="pb-1.5 text-right font-medium">Resultaat</th><th className="pb-1.5 text-right font-medium">Kosten</th></tr></thead>
              <tbody>{[...r.trades].reverse().map((t, i) => (
                <tr key={i} className="border-t border-white/[.04]"><td className="py-1">{t.entry_ts.slice(0, 10)}</td><td className="py-1">{t.exit_ts ? t.exit_ts.slice(0, 10) : <span className="text-cyan-300">open</span>}</td>
                  <td className="num py-1 text-right">{t.bars}</td><td className={`num py-1 text-right ${tone(t.ret)}`}>{pct(t.ret, 1, true)}</td><td className={`num py-1 text-right ${tone(t.pnl_eur)}`}>{eur(t.pnl_eur)}</td><td className="num py-1 text-right text-slate-400">{eur(t.costs_eur)}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="text-sm text-slate-500">Geen trades in deze periode.</p>}
      </Panel>
    </div>
  );
}
