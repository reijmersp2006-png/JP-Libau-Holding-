"use client";

import { safeUrl } from "@/lib/url";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { ago, num, pct } from "@/lib/format";
import type { DataLabel } from "@/lib/types";
import { CHART, Delta, Freshness, PageHeader, Provenance, Tabs, Unavailable } from "./ds";
import type { Bar } from "./PriceChart";
import { DataBadge, Empty, Panel, Skeleton } from "./ui";

// De grafiekbibliotheek laadt pas als het werkblad zichtbaar is (lazy), los van de rest van de pagina.
const PriceChart = dynamic(() => import("./PriceChart").then((m) => m.PriceChart), {
  ssr: false, loading: () => <Skeleton className="h-[460px]" />,
});

interface UniRow { symbol: string; asset_class: string; currency: string; tradeable_universe: boolean; intervals: string[];
  last?: number; ts?: string; ret_1d?: number; ret_30d?: number | null; label: DataLabel }
interface Quality { source: string; available: string[]; unavailable: Record<string, string> }
interface Asset {
  symbol: string; asset_class: string; currency: string; interval: string; intervals: string[]; label: DataLabel;
  last: number | null; ts: string | null; age_hours: number | null; candles: Bar[];
  indicators: { sma20: (number | null)[]; sma50: (number | null)[]; sma200: (number | null)[]; rsi14: (number | null)[] };
  stats: { available: boolean; ret?: Record<string, number | null>; vol_20d?: number | null; vol_1y?: number | null; max_drawdown_1y?: number;
    high_52w?: number; low_52w?: number; volume_20d_vs_1y?: number | null; trend?: string; rsi14?: number | null };
  quality: Quality;
  news: { id: number; title: string; source: string; source_kind: string; url: string; published_at: string; category: string;
    relevance: number | null; simulated: boolean; trace_id: string | null; workflow_id: number | null; research_priority: string | null }[];
  events: { t: number; text: string; simulated: boolean }[];
  research: { hypotheses: { id: number; title: string; status: string; source: string; created_at: string }[];
    tasks: { id: number; agent: string; kind: string; status: string; reason: string; updated_at: string }[]; note: string };
}
interface Risk { limits: { key: string; label: string; value: number }[] }
interface Radar { x: { connected: boolean; detail: string }; tokens: { symbol: string; social: { status: string; mentions_per_hour?: number; bot_risk?: number };
  safety: { status: string; checks?: { label: string; status: string }[] }; tradeable: [boolean, string] }[] }

const CLASS_NL: Record<string, string> = { crypto: "Crypto", meme: "Memecoins", stocks: "Aandelen & ETF's", metals: "Metalen", fx: "Valuta", context: "Context" };
const RANGES: [string, number][] = [["3M", 66], ["6M", 130], ["1J", 260], ["3J", 780], ["Alles", 2000]];
const ccyFmt = (v: number | null | undefined, ccy: string) =>
  v == null ? "—" : Math.abs(v) < 0.01 ? `${ccy} ${v.toPrecision(4)}` : v.toLocaleString("nl-NL", { style: "currency", currency: ccy, maximumFractionDigits: Math.abs(v) < 1 ? 6 : 2 });
/** Koers met genoeg significante cijfers, ook voor memecoins van een fractie van een cent. */
const price = (v: number | null | undefined) =>
  v == null ? "—" : Math.abs(v) < 0.01 ? v.toPrecision(3) : num(v, Math.abs(v) < 1 ? 5 : 2);

function useWatchlist() {
  // Alleen een voorkeur (lijst met symbolen) in de browser; nooit sleutels of tokens.
  const [list, setList] = useState<string[]>([]);
  useEffect(() => {
    const t = setTimeout(() => {
      try { setList(JSON.parse(localStorage.getItem("nexus.watchlist") ?? "[]")); } catch { setList([]); }
    }, 0);
    return () => clearTimeout(t);
  }, []);
  const toggle = (s: string) => setList((l) => {
    const n = l.includes(s) ? l.filter((x) => x !== s) : [...l, s];
    localStorage.setItem("nexus.watchlist", JSON.stringify(n));
    return n;
  });
  return { list, toggle };
}

export function Workstation({ classes, title, initial, intro }: { classes: string[]; title: string; initial: string; intro: string }) {
  const uni = useApi<{ items: UniRow[]; quality: Record<string, Quality> }>("/api/workstation/universe", 300_000);
  const [symbol, setSymbol] = useState(initial);
  const [interval, setInterval] = useState<"1d" | "1h">("1d");
  const [range, setRange] = useState(260);
  const [mode, setMode] = useState<"candles" | "line">("candles");
  const [ov, setOv] = useState({ sma20: false, sma50: true, sma200: true, rsi: true });
  const [cmp, setCmp] = useState("");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [sort, setSort] = useState<"name" | "1d" | "30d">("name");
  const wl = useWatchlist();

  const iv = interval;
  const asset = useApi<Asset>(`/api/workstation/asset?symbol=${encodeURIComponent(symbol)}&interval=${iv}&limit=${iv === "1h" ? 500 : range}`, 300_000);
  const cmpData = useApi<Asset>(cmp ? `/api/workstation/asset?symbol=${encodeURIComponent(cmp)}&interval=${iv}&limit=${iv === "1h" ? 500 : range}` : null, 300_000);
  const a = asset.data && asset.data.symbol === symbol && asset.data.interval === iv ? asset.data : null;

  const rows = useMemo(() => {
    const all = (uni.data?.items ?? []).filter((r) => classes.includes(r.asset_class) || (classes.includes("context") && r.asset_class === "context"));
    const f = all.filter((r) => (cat === "all" || (cat === "mine" ? wl.list.includes(r.symbol) : r.asset_class === cat))
      && r.symbol.toLowerCase().includes(q.toLowerCase()));
    return [...f].sort((x, y) => sort === "name" ? x.symbol.localeCompare(y.symbol)
      : sort === "1d" ? (y.ret_1d ?? -9) - (x.ret_1d ?? -9) : (y.ret_30d ?? -9) - (x.ret_30d ?? -9));
  }, [uni.data, classes, cat, q, sort, wl.list]);
  const peers = (uni.data?.items ?? []).filter((r) => r.symbol !== symbol);

  const overlays = useMemo(() => !a ? [] : ([
    ov.sma20 && { key: "SMA 20", color: CHART.ice, values: a.indicators.sma20 },
    ov.sma50 && { key: "SMA 50", color: CHART.violet, values: a.indicators.sma50 },
    ov.sma200 && { key: "SMA 200", color: CHART.amber, values: a.indicators.sma200 },
  ].filter(Boolean) as { key: string; color: string; values: (number | null)[] }[]), [a, ov]);
  const compare = useMemo(() => (cmp && cmpData.data && cmpData.data.symbol === cmp ? { symbol: cmp, bars: cmpData.data.candles } : null), [cmp, cmpData.data]);

  const classTabs: [string, string][] = [["all", "Alle"], ...classes.filter((c) => c !== "context").map((c) => [c, CLASS_NL[c]] as [string, string]), ["mine", "Mijn lijst"]];

  return (
    <div className="page-in">
      <PageHeader eyebrow={`Trading Workstation · ${title}`} title={symbol}
        sub={intro}
        meta={a ? <><Freshness label={a.label} ts={a.ts} note={a.label === "DELAYED" ? "vertraagd, geen streaming" : undefined} />
          <span className="text-slate-500">{CLASS_NL[a.asset_class]} · {a.currency} · bron {a.quality.source}</span></> : null}
        right={<span className="chip">Alleen onderzoek · geen orders vanuit dit scherm</span>} />

      <div className="grid gap-5 xl:grid-cols-[230px_minmax(0,1fr)] min-[1760px]:grid-cols-[240px_minmax(0,1fr)_360px]">
        {/* Watchlist */}
        <Panel className="!p-3 order-2 xl:order-none xl:row-span-2 xl:self-start min-[1760px]:row-span-1">
          <label className="sr-only" htmlFor="ws-search">Zoek instrument</label>
          <input id="ws-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Zoeken…"
            className="mb-2 w-full rounded-md border border-white/[.08] bg-white/[.02] px-2.5 py-1.5 text-[12.5px] text-slate-200 placeholder:text-slate-600" />
          <div className="mb-2"><Tabs label="Categorie" value={cat} onChange={setCat} items={classTabs} /></div>
          <div className="mb-1 flex items-center justify-between px-1 text-[11px] text-slate-500">
            <span>{rows.length} instrumenten</span>
            <select aria-label="Sorteren" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="bg-transparent text-slate-400">
              <option value="name">naam</option><option value="1d">1 dag</option><option value="30d">30 dagen</option>
            </select>
          </div>
          {!uni.data ? <Skeleton className="h-64" /> : !rows.length ? <Empty>{cat === "mine" ? "Je lijst is leeg. Gebruik ☆ om instrumenten toe te voegen." : "Niets gevonden."}</Empty> : (
            <ul className="max-h-[560px] overflow-y-auto">
              {rows.map((r) => (
                <li key={r.symbol} className={`group flex items-center gap-1 rounded-md ${r.symbol === symbol ? "bg-white/[.06]" : "hover:bg-white/[.025]"}`}>
                  <button onClick={() => setSymbol(r.symbol)} aria-current={r.symbol === symbol} className="flex min-w-0 flex-1 items-center justify-between gap-2 px-2 py-1.5 text-left">
                    <span className="min-w-0"><span className="block truncate text-[12.5px] text-slate-100">{r.symbol}</span>
                      <span className="block truncate text-[10.5px] text-slate-500" title={r.tradeable_universe ? undefined : "Niet in het handelsuniversum: alleen onderzoek"}>{CLASS_NL[r.asset_class]}{r.tradeable_universe || r.asset_class === "context" ? "" : " · extra"}{r.intervals.includes("1h") ? "" : " · alleen dag"}</span></span>
                    <span className="text-right"><span className="num block text-[12px] text-slate-300">{price(r.last)}</span><Delta v={r.ret_1d} className="block text-[11px]" /></span>
                  </button>
                  <button onClick={() => wl.toggle(r.symbol)} aria-label={`${r.symbol} ${wl.list.includes(r.symbol) ? "uit" : "in"} mijn lijst`}
                    className={`px-1.5 text-[13px] ${wl.list.includes(r.symbol) ? "text-amber-300" : "text-slate-600 opacity-0 group-hover:opacity-100 focus:opacity-100"}`}>{wl.list.includes(r.symbol) ? "★" : "☆"}</button>
                </li>
              ))}
            </ul>
          )}
          <p className="t-micro mt-3">extra = buiten het handelsuniversum, alleen onderzoek</p>
        </Panel>

        {/* Grafiek */}
        <div className="order-1 min-w-0 space-y-5 xl:order-none">
          <Panel className="!p-4">
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="flex items-baseline gap-3">
                <span className="t-kpi">{a ? ccyFmt(a.last, a.currency) : "—"}</span>
                {a?.stats.ret && <Delta v={a.stats.ret["1d"]} className="text-[13px]" />}
              </div>
              <div className="ml-auto flex flex-wrap items-center gap-1.5">
                {(["1h", "1d"] as const).map((x) => {
                  const ok = a ? a.intervals.includes(x) : true;
                  return <button key={x} className="btn px-2 py-1" aria-pressed={iv === x} disabled={!ok} title={ok ? undefined : "geen opgeslagen candles voor deze tijdschaal"} onClick={() => setInterval(x)}>{x === "1h" ? "1 uur" : "1 dag"}</button>;
                })}
                <span className="mx-1 h-4 w-px bg-white/10" />
                {iv === "1d" && RANGES.map(([l, n]) => <button key={l} className="btn px-2 py-1" aria-pressed={range === n} onClick={() => setRange(n)}>{l}</button>)}
                <span className="mx-1 h-4 w-px bg-white/10" />
                <button className="btn px-2 py-1" aria-pressed={mode === "candles"} onClick={() => setMode(mode === "candles" ? "line" : "candles")}>{mode === "candles" ? "Candles" : "Lijn"}</button>
              </div>
            </div>
            <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[12px]">
              {([["sma20", "SMA 20", CHART.ice], ["sma50", "SMA 50", CHART.violet], ["sma200", "SMA 200", CHART.amber], ["rsi", "RSI 14", CHART.ice]] as const).map(([k, l, c]) => (
                <button key={k} className="btn px-2 py-0.5 text-[11.5px]" aria-pressed={ov[k]} onClick={() => setOv({ ...ov, [k]: !ov[k] })}>
                  <span className="h-0.5 w-3 rounded" style={{ background: c }} />{l}</button>
              ))}
              <label className="ml-auto flex items-center gap-2 text-slate-500">Vergelijk
                <select value={cmp} onChange={(e) => setCmp(e.target.value)} className="rounded-md border border-white/[.08] bg-[#0F1217] px-2 py-1 text-slate-200">
                  <option value="">—</option>
                  {peers.map((p) => <option key={p.symbol} value={p.symbol}>{p.symbol}</option>)}
                </select>
              </label>
            </div>
            {asset.error && !a ? <Empty>Koersen niet te laden: {asset.error}</Empty> : !a ? <Skeleton className="h-[460px]" /> : (
              <PriceChart bars={a.candles} overlays={overlays} rsi={ov.rsi ? a.indicators.rsi14 : null} intraday={iv === "1h"}
                markers={a.events} compare={compare} mode={mode} height={480} />
            )}
            <p className="t-micro mt-2">
              {iv === "1h" ? `Uurkoersen: alleen de opgeslagen ${a?.candles.length ?? 0} uren; geen langere geschiedenis.` : "Dagkoersen uit de opslag."} {compare ? "Vergelijking in % vanaf het eerste gemeenschappelijke punt." : ""} Markeringen: N = nieuws, sim = gesimuleerd.
            </p>
          </Panel>

          {a && <Stats a={a} />}
        </div>

        {/* Onderzoek: rechts op brede schermen, anders onder de grafiek */}
        <div className="order-3 min-w-0 xl:order-none xl:col-start-2 min-[1760px]:col-start-3 min-[1760px]:row-start-1">
          {a ? <ResearchPanel a={a} /> : <Skeleton className="h-[600px]" />}
        </div>
      </div>
    </div>
  );
}

function Stats({ a }: { a: Asset }) {
  const s = a.stats;
  if (!s.available || !s.ret) return <Panel title="Gemeten kenmerken"><Empty>Te weinig dagkoersen (minder dan 31) voor statistiek.</Empty></Panel>;
  const cells: [string, React.ReactNode, string?][] = [
    ["1 dag", <Delta key="a" v={s.ret["1d"]} />], ["7 dagen", <Delta key="b" v={s.ret["7d"]} />], ["30 dagen", <Delta key="c" v={s.ret["30d"]} />],
    ["90 dagen", <Delta key="d" v={s.ret["90d"]} />], ["1 jaar", <Delta key="e" v={s.ret["1y"]} />], ["Dit jaar", <Delta key="f" v={s.ret.ytd} />],
    ["Volatiliteit 20d", pct(s.vol_20d, 0), "p.j."], ["Volatiliteit 1j", pct(s.vol_1y, 0), "p.j."],
    ["Grootste daling 1j", pct(s.max_drawdown_1y, 1)], ["52-weeks bereik", `${price(s.low_52w)} – ${price(s.high_52w)}`],
    ["Volume 20d vs 1j", <Delta key="g" v={s.volume_20d_vs_1y} digits={0} />], ["RSI 14", num(s.rsi14, 0)],
  ];
  return (
    <Panel title="Gemeten kenmerken" action={<span className="flex items-center gap-2"><Provenance kind="measured" /><span className="t-micro">vaste code, dagkoersen</span></span>}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px] sm:grid-cols-3 2xl:grid-cols-6">
        {cells.map(([k, v, sub]) => <div key={k}><dt className="t-label">{k}</dt><dd className="num mt-0.5 text-slate-100">{v}{sub && <span className="t-micro ml-1">{sub}</span>}</dd></div>)}
      </dl>
      <p className="mt-3 text-[12px] text-slate-400">Trend: {s.trend}. Dit is een beschrijving van het verleden, geen signaal.</p>
    </Panel>
  );
}

function ResearchPanel({ a }: { a: Asset }) {
  const [tab, setTab] = useState<"research" | "news" | "risk" | "data">("research");
  const risk = useApi<Risk>("/api/risk", 300_000);
  const radar = useApi<Radar>("/api/social/radar", 300_000);
  const tok = a.asset_class === "meme" ? radar.data?.tokens.find((t) => t.symbol === a.symbol) : undefined;
  return (
    <Panel className="!p-4">
      <div className="mb-3"><Tabs label="Onderzoekspaneel" value={tab} onChange={setTab}
        items={[["research", "Onderzoek"], ["news", `Nieuws · ${a.news.length}`], ["risk", "Risico"], ["data", "Data"]]} /></div>

      {tab === "research" && (
        <div className="space-y-4 text-[12.5px]">
          <section>
            <div className="mb-1.5 flex items-center justify-between"><span className="t-label">AI-analyse en scenario&apos;s</span><Provenance kind="ai" /></div>
            <p className="text-slate-500">Geen AI-analyse voor dit instrument: er is nog geen Council-run met een verbonden aanbieder. Alternatieve scenario&apos;s verschijnen hier pas na een echt debat, met de bronverwijzingen erbij.</p>
          </section>
          <section>
            <div className="mb-1.5 flex items-center justify-between"><span className="t-label">Hypothesen</span><Provenance kind="measured" /></div>
            {a.research.hypotheses.length ? (
              <ul className="space-y-1.5">{a.research.hypotheses.map((h) => (
                <li key={h.id} className="flex justify-between gap-2"><Link href="/evolution" className="text-slate-200 hover:text-white">#{h.id} {h.title}</Link><span className="chip">{h.status}</span></li>))}</ul>
            ) : <p className="text-slate-500">Geen hypothesen die dit instrument noemen.</p>}
          </section>
          <section>
            <div className="mb-1.5 t-label">Taken van agenten</div>
            {a.research.tasks.length ? (
              <ul className="space-y-1.5">{a.research.tasks.map((t) => (
                <li key={t.id}><div className="text-slate-200">{t.agent} · {t.kind} <span className="chip ml-1">{t.status}</span></div><div className="text-slate-500">{t.reason} · {ago(t.updated_at)}</div></li>))}</ul>
            ) : <p className="text-slate-500">Geen taken over dit instrument.</p>}
          </section>
          {tok && (
            <section>
              <div className="mb-1.5 t-label">Social en tokenveiligheid</div>
              <p className="text-slate-400">X: {tok.social.status === "ok" ? `${num(tok.social.mentions_per_hour, 1)} vermeldingen/uur, botrisico ${pct(tok.social.bot_risk, 0)}` : "niet verbonden, geen metingen"}.</p>
              <p className="text-slate-400">Veiligheid: {tok.safety.status === "not_applicable" ? "geen tokencontract (eigen keten)" : tok.safety.status}. Handel: {tok.tradeable[1]}.</p>
              <Link href="/social" className="text-cyan-300 hover:text-cyan-200">Social Radar</Link>
            </section>
          )}
          <p className="t-micro">{a.research.note} Strategieresultaten staan in het <Link href="/evolution" className="text-cyan-300">Evolution Lab</Link>.</p>
        </div>
      )}

      {tab === "news" && (a.news.length ? (
        <ul className="divide-y divide-white/[.05] text-[12.5px]">
          {a.news.map((n) => (
            <li key={n.id} className="py-2.5">
              <a href={safeUrl(n.url)} target="_blank" rel="noreferrer noopener" className="text-slate-100 hover:text-white">{n.title}</a>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                <span className="chip">{n.source_kind === "fixture" ? "fixture" : n.source_kind === "official" ? "officieel" : n.source_kind}</span>
                {n.simulated && <DataBadge label="SIMULATED" />}
                <span>{n.source} · {ago(n.published_at)}</span>
                {n.trace_id && <Link href={`/decisions?trace=${n.workflow_id}`} className="text-cyan-300">spoor {n.trace_id}</Link>}
              </div>
            </li>
          ))}
        </ul>
      ) : <Empty>Geen nieuws gekoppeld aan {a.symbol}. Zonder bereikbare feeds blijft dit leeg.</Empty>)}

      {tab === "risk" && (
        <div className="space-y-3 text-[12.5px]">
          <p className="text-slate-400">Gemeten beweeglijkheid {pct(a.stats.vol_20d, 0)} per jaar (20 dagen), grootste daling in een jaar {pct(a.stats.max_drawdown_1y, 1)}.</p>
          <div className="t-label">Regels van de Risk Guardian (vast, door geen agent te wijzigen)</div>
          {risk.data ? (
            <ul className="space-y-1">{risk.data.limits.filter((l) => ["max_position_pct", "max_risk_per_trade_pct", "max_correlated_pct", "max_meme_pct", "max_spread_pct"].includes(l.key))
              .map((l) => <li key={l.key} className="flex justify-between"><span className="text-slate-300">{l.label}</span><span className="num text-slate-200">{pct(l.value, 1)}</span></li>)}</ul>
          ) : <Skeleton className="h-24" />}
          <p className="t-micro">Spread en orderboekdiepte ontbreken in deze data: de spreadregel is hier niet te controleren. Elk voorstel gaat altijd langs de Risk Guardian.</p>
        </div>
      )}

      {tab === "data" && (
        <div className="space-y-3 text-[12.5px]">
          <div><div className="t-label">Bron</div><div className="text-slate-200">{a.quality.source}</div></div>
          <div><div className="t-label mb-1">Beschikbaar</div><ul className="space-y-0.5 text-slate-300">{a.quality.available.map((x) => <li key={x}>· {x}</li>)}</ul></div>
          <div><div className="t-label mb-1">Niet beschikbaar</div><Unavailable items={a.quality.unavailable} /></div>
          <p className="t-micro">Tijdschalen: {a.intervals.join(", ") || "geen"}. Laatste candle {a.age_hours != null ? `${num(a.age_hours, 0)} uur oud` : "—"}.</p>
        </div>
      )}
    </Panel>
  );
}
