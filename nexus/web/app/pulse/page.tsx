"use client";

import Link from "next/link";
import { useState } from "react";
import { Delta, Freshness, KpiCell, KpiStrip, PageHeader, Provenance, Tabs } from "@/components/ds";
import { Empty, Panel, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { num, pct } from "@/lib/format";
import type { DataLabel } from "@/lib/types";

interface Row { symbol: string; asset_class: string; ts: string; label: DataLabel; ret_1d: number; ret_7d: number; ret_30d: number; vol_60d_daily: number; move_z: number }
interface Overview {
  as_of: string | null; label: DataLabel; vix: number | null; note: string; regime: { summary: string; method: string };
  classes: { asset_class: string; n: number; ret_1d: number; ret_7d: number; ret_30d: number; breadth_up_1d: number }[];
  rows: Row[]; movers: Row[]; correlation: { symbols: string[]; matrix: (number | null)[][]; days: number };
}
const CLASS_NL: Record<string, string> = { crypto: "Crypto", meme: "Memecoins", stocks: "Aandelen & ETF's", metals: "Metalen", fx: "Valuta", context: "Indices, rente, grondstoffen" };
const ORDER = ["stocks", "crypto", "meme", "metals", "fx", "context"];
const HREF: Record<string, string> = { crypto: "/crypto", meme: "/meme", stocks: "/stocks", metals: "/stocks", fx: "/forex", context: "/stocks" };

/** Kleur op schaal van de eigen beweeglijkheid: een tegel is pas fel als de beweging ongewoon is voor dat instrument. */
function tile(r: number, sd: number) {
  const z = Math.max(-3, Math.min(3, r / (sd || 1e-9)));
  const a = Math.min(0.55, Math.abs(z) / 3 * 0.55);
  return z >= 0 ? `rgba(76,196,149,${a})` : `rgba(226,90,100,${a})`;
}
function corrColor(v: number | null) {
  if (v == null) return "transparent";
  return v >= 0 ? `rgba(140,203,242,${Math.abs(v) * 0.75})` : `rgba(221,178,92,${Math.abs(v) * 0.75})`;
}

export default function Page() {
  const { data, error } = useApi<Overview>("/api/market/overview", 300_000);
  const [h, setH] = useState<"ret_1d" | "ret_7d" | "ret_30d">("ret_1d");
  const [hover, setHover] = useState<[number, number] | null>(null);
  if (error && !data) return <Empty>Market Pulse niet te laden: {error}</Empty>;
  if (!data) return <Skeleton className="h-[600px]" />;
  const scale = h === "ret_1d" ? 1 : h === "ret_7d" ? Math.sqrt(7) : Math.sqrt(30);
  const eq = data.classes.find((c) => c.asset_class === "stocks"), cr = data.classes.find((c) => c.asset_class === "crypto");
  const unusual = data.rows.filter((r) => Math.abs(r.move_z) >= 2).length;
  const C = data.correlation;

  return (
    <div className="page-in">
      <PageHeader eyebrow="Markten" title="Global Market Pulse"
        sub="Alle opgeslagen instrumenten in één overzicht: rendement per klasse, ongewone bewegingen ten opzichte van de eigen beweeglijkheid, en hoe sterk markten samen bewegen. Dagkoersen, geen streaming."
        meta={<><Freshness label={data.label} ts={data.as_of} /><Provenance kind="measured" /></>} />

      <div className="space-y-5">
        <KpiStrip cols="md:grid-cols-5">
          <KpiCell label="Aandelen · 1 dag" value={<Delta v={eq?.ret_1d} />} sub={eq ? `${pct(eq.breadth_up_1d, 0)} stijgt · ${eq.n} instrumenten` : "geen data"} />
          <KpiCell label="Crypto · 30 dagen" value={<Delta v={cr?.ret_30d} />} sub={cr ? `${cr.n} munten, gelijk gewogen` : "geen data"} />
          <KpiCell label="VIX" value={num(data.vix, 1)} sub={data.vix == null ? "geen data" : data.vix >= 20 ? "verhoogde onrust" : "rustig"} />
          <KpiCell label="Ongewone bewegingen" value={unusual} sub="|beweging| ≥ 2σ van eigen 60 dagen" />
          <KpiCell label="Regime" value={<span className="text-[13px] font-normal leading-snug text-slate-200">{data.regime.summary}</span>} sub={data.regime.method} />
        </KpiStrip>

        <Panel title="Heatmap per activaklasse" action={<Tabs label="Periode" value={h} onChange={setH} items={[["ret_1d", "1 dag"], ["ret_7d", "7 dagen"], ["ret_30d", "30 dagen"]]} />}>
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {ORDER.filter((c) => data.rows.some((r) => r.asset_class === c)).map((c) => (
              <section key={c}>
                <div className="mb-2 flex items-baseline justify-between"><Link href={HREF[c]} className="eyebrow hover:text-slate-300">{CLASS_NL[c]}</Link>
                  <Delta v={data.classes.find((x) => x.asset_class === c)?.[h]} className="text-[12px]" /></div>
                <div className="grid grid-cols-3 gap-1 sm:grid-cols-4">
                  {data.rows.filter((r) => r.asset_class === c).sort((a, b) => a.symbol.localeCompare(b.symbol)).map((r) => (
                    <div key={r.symbol} title={`${r.symbol}: ${pct(r[h], 2, true)} · beweging ${num(r.move_z, 1)}σ (1 dag) · ${r.label}`}
                      className="rounded-md border border-white/[.05] px-2 py-1.5" style={{ background: tile(r[h], r.vol_60d_daily * scale) }}>
                      <div className="truncate text-[11.5px] text-slate-100">{r.symbol}</div>
                      <div className="num text-[11.5px] text-slate-200">{pct(r[h], 1, true)}</div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
          <p className="t-micro mt-4">Kleursterkte = beweging gedeeld door de eigen beweeglijkheid (60 dagen), dus 2% bij een rustig aandeel kleurt sterker dan 2% bij een memecoin. Groen = stijging, rood = daling.</p>
        </Panel>

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
          <Panel title="Correlatie van dagrendementen" action={<span className="t-label">{C.days} dagen · {C.symbols.length} instrumenten</span>}>
            {C.symbols.length < 2 ? <Empty>Te weinig gemeenschappelijke dagen.</Empty> : (
              <div className="overflow-x-auto">
                <svg viewBox={`0 0 ${90 + C.symbols.length * 18} ${90 + C.symbols.length * 18}`} className="w-full min-w-[560px] max-w-[760px]" role="img" aria-label="Correlatiematrix">
                  {C.symbols.map((s, i) => (
                    <g key={s}>
                      <text x={86} y={96 + i * 18} textAnchor="end" className={`text-[8px] ${hover?.[0] === i ? "fill-white" : "fill-slate-500"}`}>{s}</text>
                      <text transform={`translate(${96 + i * 18},86) rotate(-60)`} className={`text-[8px] ${hover?.[1] === i ? "fill-white" : "fill-slate-500"}`}>{s}</text>
                    </g>
                  ))}
                  {C.matrix.map((row, i) => row.map((v, j) => (
                    <rect key={`${i}-${j}`} x={90 + j * 18} y={90 + i * 18} width="17" height="17" rx="2" fill={corrColor(i === j ? null : v)}
                      stroke={hover && hover[0] === i && hover[1] === j ? "#F4F6FA" : "rgba(255,255,255,.04)"}
                      onMouseEnter={() => setHover([i, j])} onMouseLeave={() => setHover(null)}>
                      <title>{`${C.symbols[i]} × ${C.symbols[j]}: ${v == null ? "—" : num(v, 2)}`}</title>
                    </rect>
                  )))}
                </svg>
              </div>
            )}
            <p className="t-micro mt-2">{hover ? `${C.symbols[hover[0]]} × ${C.symbols[hover[1]]}: ${num(C.matrix[hover[0]][hover[1]], 2)}` : "Beweeg over een vak voor de waarde."} Blauw = bewegen samen, goud = tegengesteld. Correlatie verandert in de tijd en is geen voorspelling.</p>
          </Panel>
          <Panel title="Grootste bewegers · 1 dag" action={<Provenance kind="measured" />}>
            <table className="dtable">
              <thead><tr><th>Instrument</th><th className="r">1 dag</th><th className="r">σ</th><th className="r">30 dagen</th></tr></thead>
              <tbody>
                {data.movers.map((r) => (
                  <tr key={r.symbol}><td><Link href={HREF[r.asset_class]} className="text-slate-100 hover:text-white">{r.symbol}</Link> <span className="t-micro">{CLASS_NL[r.asset_class]}</span></td>
                    <td className="r"><Delta v={r.ret_1d} /></td><td className="r text-slate-300">{num(r.move_z, 1)}</td><td className="r"><Delta v={r.ret_30d} /></td></tr>
                ))}
              </tbody>
            </table>
            <p className="t-micro mt-3">Nieuwskatalysatoren: zie de <Link href="/news" className="text-cyan-300">News Reactor</Link>. Zonder bereikbare feeds zijn er geen echte koppelingen tussen nieuws en bewegingen.</p>
          </Panel>
        </div>
        <p className="t-micro">{data.note}</p>
      </div>
    </div>
  );
}
