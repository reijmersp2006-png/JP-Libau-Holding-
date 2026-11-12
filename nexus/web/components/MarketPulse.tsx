"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { num, pct, time, tone } from "@/lib/format";
import type { DataLabel } from "@/lib/types";
import { DataBadge, Empty, Segmented, Skeleton } from "./ui";

interface Row {
  symbol: string; asset_class: string; currency?: string; last?: number; ts?: string; ret_1d?: number; ret_7d?: number;
  ret_30d?: number; vol_annual?: number; move_z?: number; spark?: number[]; label: DataLabel;
}
const CLASS: Record<string, string> = { stocks: "Aandelen & ETF's", crypto: "Crypto", meme: "Memecoins", metals: "Metalen", fx: "Valuta" };
type H = "ret_1d" | "ret_7d" | "ret_30d";

function Line({ v }: { v: number[] }) {
  if (v.length < 2) return null;
  const min = Math.min(...v), max = Math.max(...v), s = max - min || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * 100},${28 - ((x - min) / s) * 26}`).join(" ");
  const up = v[v.length - 1] >= v[0];
  return <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-7 w-24" aria-hidden><polyline points={pts} fill="none" stroke={up ? "#4CC495" : "#E25A64"} strokeWidth="1.3" vectorEffect="non-scaling-stroke" /></svg>;
}

/** Global Market Pulse: echte dagkoersen per markt. Kleurintensiteit = beweging t.o.v. de eigen normale beweeglijkheid. */
export function MarketPulse() {
  const { data, loading, error } = useApi<{ items: Row[]; note: string }>("/api/pulse", 120_000);
  const [h, setH] = useState<H>("ret_1d");
  if (loading && !data) return <Skeleton className="h-72" />;
  if (error && !data) return <Empty>Marktdata niet te laden: {error}</Empty>;
  const rows = (data?.items ?? []).filter((r) => r.last != null);
  if (!rows.length) return <Empty>Geen dagkoersen in de database. Er wordt niets ingevuld.</Empty>;
  const up = rows.filter((r) => (r.ret_1d ?? 0) > 0).length;
  const big = rows.filter((r) => Math.abs(r.move_z ?? 0) >= 2).length;
  const latest = rows.reduce((a, r) => (r.ts && r.ts > a ? r.ts : a), "");
  const classes = [...new Set(rows.map((r) => r.asset_class))];
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="flex gap-8">
          <div><div className="caption">Breedte vandaag</div><div className="num mt-1 text-xl font-semibold text-white">{up}<span className="text-slate-500"> / {rows.length} hoger</span></div></div>
          <div><div className="caption">Ongewone bewegingen</div><div className="num mt-1 text-xl font-semibold text-white">{big}<span className="text-slate-500 text-sm font-normal"> ≥ 2σ</span></div></div>
          <div><div className="caption">Laatste slot</div><div className="mt-1 text-sm text-slate-300">{time(latest)}</div></div>
        </div>
        <Segmented label="Horizon" value={h} onChange={setH} options={[["ret_1d", "1 dag"], ["ret_7d", "7 dagen"], ["ret_30d", "30 dagen"]]} />
      </div>
      <div className="grid gap-x-8 gap-y-6 md:grid-cols-2 2xl:grid-cols-3">
        {classes.map((c) => (
          <section key={c} aria-label={CLASS[c] ?? c}>
            <div className="eyebrow mb-2">{CLASS[c] ?? c}</div>
            <ul className="divide-y divide-white/[.05]">
              {rows.filter((r) => r.asset_class === c).map((r) => {
                const v = r[h] ?? 0;
                const z = Math.min(1, Math.abs(r.move_z ?? 0) / 3);
                return (
                  <li key={r.symbol} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-medium text-slate-100">{r.symbol}</div>
                      <div className="num text-[11.5px] text-slate-500">{r.currency} {num(r.last, (r.last ?? 0) < 1 ? 6 : 2)}</div>
                    </div>
                    <Line v={r.spark ?? []} />
                    <span className={`num w-16 rounded px-1.5 py-0.5 text-right text-[12.5px] ${tone(v)}`}
                      style={{ background: h === "ret_1d" ? `rgba(${v >= 0 ? "76,196,149" : "226,90,100"},${0.04 + z * 0.16})` : undefined }}>
                      {pct(v, 1, true)}
                    </span>
                    <DataBadge label={r.label} />
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
      <p className="mt-4 text-[11.5px] text-slate-600">{data?.note}. Achtergrond bij 1 dag: sterkte van de beweging ten opzichte van de eigen beweeglijkheid van de afgelopen 60 dagen.</p>
    </div>
  );
}
