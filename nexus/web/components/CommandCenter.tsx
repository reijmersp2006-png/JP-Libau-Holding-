"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import { ago, eur, num, pct, time, tone } from "@/lib/format";
import type { CommandCenter as CC } from "@/lib/types";
import { EnvBanner } from "./Banner";
import { BriefingCard } from "./BriefingCard";
import { DecisionFlow } from "./DecisionFlow";
import { EquityChart } from "./EquityChart";
import { KillSwitch } from "./KillSwitch";
import { MarketPulse } from "./MarketPulse";
import { NeuralCore } from "./NeuralCore";
import { DataBadge, Empty, ErrorBox, Kpi, Meter, Panel, Skeleton, StatusDot } from "./ui";

/* Gedempte afdelingskleuren: ijsblauw en violet voor de grote desks, de rest grijstinten en metaal. */
const DESK_COLORS: Record<string, string> = {
  crypto: "#8CCBF2", meme: "#A79BEA", stocks: "#B4BCC9", metals: "#DDB25C", fx: "#4CC495", cash: "#4A525F",
};
const MODE_TEXT = { research: "Research", paper: "Paper trading", live: "Live" } as const;

/**
 * Command Center volgens design 4.1: binnen vijf seconden leesbaar.
 * Bovenaan één rij kerncijfers, daaronder de grote vermogenscurve met de besturing,
 * dan het AI-hoofdkwartier (Neural Core, Decision Flow, briefing), daarna markt en posities.
 * Alles komt uit echte endpoints; ontbreekt iets, dan staat er "geen data".
 */
export function CommandCenter() {
  const { data, error, loading, refresh, updatedAt } = useApi<CC>("/api/command-center", 30_000);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  if (!data) return null;
  const p = data.portfolio;
  const worstRisk = data.risk.length ? data.risk.reduce((a, b) => (b.utilization > a.utilization ? b : a)) : null;
  const gatePassed = data.controls.live_gate.filter((g) => g.passed).length;
  const vetoes = data.proposals.filter((x) => x.status === "vetoed").length;

  return (
    <div className="space-y-5">
      <EnvBanner env={data.environment} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">JP-libau Holding · NEXUS</div>
          <h1 className="title-lg mt-1.5">Command Center</h1>
          <p className="caption mt-1.5">
            Stand van {time(data.as_of ?? data.generated_at)}
            {updatedAt && <> · opgehaald {ago(updatedAt.toISOString())}</>}
            {error && <span className="text-amber-300"> · laatste verversing mislukt</span>}
          </p>
        </div>
        <div className="flex items-center gap-4 text-[12.5px]">
          <span className="text-slate-400">Modus <b className="font-medium text-slate-100">{MODE_TEXT[data.controls.mode]}</b></span>
          <span className="text-slate-400">Live handelen <b className="font-medium text-slate-100">uit</b></span>
          <Link href="/risk" className="text-slate-400 hover:text-slate-200">Live-poort <b className="num font-medium text-slate-100">{gatePassed}/{data.controls.live_gate.length}</b></Link>
        </div>
      </header>

      {/* 1 · Kerncijfers: het antwoord op "hoe staan we ervoor" */}
      <section aria-label="Kerncijfers" className="panel fade-up grid grid-cols-2 gap-x-6 gap-y-5 p-5 md:grid-cols-3 xl:grid-cols-6">
        {p ? (
          <>
            <div className="col-span-2 md:col-span-1 xl:col-span-1">
              <div className="caption flex items-center gap-2">Vermogen holding-bots <DataBadge label={p.label} /></div>
              <div className="display num mt-2 text-[34px]">{eur(p.equity_eur, 0)}</div>
              <div className="num mt-1.5 text-[12px] text-slate-500">start {eur(p.capital_eur, 0)} nepgeld · {p.days_active} dagen</div>
            </div>
            <Kpi label="Resultaat sinds start" value={pct(p.pnl_pct, 2, true)} tone={tone(p.pnl_eur)} sub={eur(p.pnl_eur)} />
            <Kpi label="Vandaag" value={pct(p.day_pnl_pct, 2, true)} tone={tone(p.day_pnl_pct)} sub="t.o.v. 24 uur terug" />
            <Kpi label="Drawdown" value={pct(-p.drawdown, 2)} tone={p.drawdown > 0 ? "text-rose-400" : "text-white"} sub={`top ${eur(p.peak_eur, 0)}`} />
            <Kpi label="Zwaarste risicolimiet" href="/risk"
              value={worstRisk ? pct(worstRisk.utilization, 0) : "—"}
              tone={worstRisk && worstRisk.utilization >= 1 ? "text-rose-400" : worstRisk && worstRisk.utilization >= 0.7 ? "text-amber-300" : "text-white"}
              sub={worstRisk ? worstRisk.label : "geen meting"} />
            <Kpi label="Voorstellen / veto's" href="/execution" value={`${data.proposals.length} / ${vetoes}`}
              sub={`${data.fills_today ?? 0} paper-trades vandaag`} />
          </>
        ) : <div className="col-span-full"><Empty>Geen portefeuilledata. Er worden geen getallen verzonnen.</Empty></div>}
      </section>

      {/* 2 · Grote curve + besturing */}
      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <Panel title="Vermogen en drawdown" label={p?.label ?? "UNAVAILABLE"}
          action={p && <span className="caption">stippellijn = startkapitaal · koop-en-houd {p.benchmark_eur != null ? eur(p.benchmark_eur, 0) : "—"}</span>}>
          {p ? (
            <>
              <EquityChart curve={p.equity_curve} capital={p.capital_eur} height={360} />
              <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-white/[.05] pt-4 text-[13px] sm:grid-cols-4">
                <Fact k="Gerealiseerd" v={eur(p.realized_eur)} c={tone(p.realized_eur)} />
                <Fact k="Ongerealiseerd" v={eur(p.unrealized_eur)} c={tone(p.unrealized_eur)} />
                <Fact k="Kosten totaal" v={eur(p.fees_eur)} />
                <Fact k="Verschil met koop-en-houd" v={p.benchmark_eur != null ? eur(p.equity_eur - p.benchmark_eur) : "—"}
                  c={p.benchmark_eur != null ? tone(p.equity_eur - p.benchmark_eur) : ""} />
              </dl>
            </>
          ) : <Empty>Geen curve zonder data.</Empty>}
        </Panel>

        <div className="space-y-5">
          <Panel title="Besturing">
            <div className="space-y-3">
              {data.nexus_paper && (
                <Link href="/execution" className="block rounded-lg border border-white/[.06] p-3 text-[12.5px] transition-colors hover:border-white/[.12]">
                  <div className="flex items-center justify-between"><span className="text-slate-400">NEXUS paper-account</span><DataBadge label={data.nexus_paper.label} /></div>
                  <div className="num mt-1.5 flex justify-between text-[14px]"><span className="text-white">{eur(data.nexus_paper.equity_eur)}</span>
                    <span className={tone(data.nexus_paper.pnl_eur)}>{eur(data.nexus_paper.pnl_eur)}</span></div>
                  <div className="text-slate-500">{data.nexus_paper.positions} posities · {data.nexus_paper.open_orders} open orders</div>
                </Link>
              )}
              <KillSwitch status={data.controls.kill} onChange={refresh} />
            </div>
          </Panel>
          <Panel title="Verdeling" label={p?.label ?? "UNAVAILABLE"}>
            {data.allocation.length ? (
              <>
                <div className="mb-4 flex h-1.5 gap-px overflow-hidden rounded-full">
                  {data.allocation.map((a) => (
                    <div key={a.key} title={`${a.name} ${pct(a.pct, 1)}`} style={{ width: `${a.pct * 100}%`, background: DESK_COLORS[a.key] ?? "#6C7584" }} />
                  ))}
                </div>
                <ul className="space-y-2">
                  {data.allocation.map((a) => (
                    <li key={a.key} className="flex items-center justify-between text-[13px]">
                      <span className="flex items-center gap-2 text-slate-300"><span className="h-2 w-2 rounded-full" style={{ background: DESK_COLORS[a.key] ?? "#6C7584" }} />{a.name}</span>
                      <span className="num text-slate-200">{eur(a.value_eur, 0)} <span className="ml-1 text-slate-500">{pct(a.pct, 1)}</span></span>
                    </li>
                  ))}
                </ul>
              </>
            ) : <Empty>Geen posities.</Empty>}
          </Panel>
        </div>
      </div>

      {/* 3 · AI-hoofdkwartier: wie doet wat, en hoe loopt een beslissing */}
      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <Panel title="Neural Core" action={<Link href="/hq" className="text-[12px] text-cyan-300 hover:text-cyan-200">AI Headquarters</Link>}>
          <NeuralCore compact />
        </Panel>
        <div className="space-y-5">
          <Panel title="AI Decision Flow" action={<span className="caption">nieuws → analyse → risico → voorstel</span>}>
            <DecisionFlow />
          </Panel>
          <Panel title="Executive briefing">
            <BriefingCard />
          </Panel>
        </div>
      </div>

      {/* 4 · Global Market Pulse */}
      <Panel title="Global Market Pulse" action={<Link href="/radar" className="text-[12px] text-cyan-300 hover:text-cyan-200">Market Radar</Link>}>
        <MarketPulse />
      </Panel>

      {/* 5 · Posities + risico */}
      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        <Panel title={`Actieve posities · ${data.positions.length}`} label={p?.label ?? "UNAVAILABLE"}>
          {data.positions.length ? (
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead><tr className="caption text-left">
                  <th className="px-1 pb-2.5 font-normal">Instrument</th><th className="pb-2.5 font-normal">Afdeling</th>
                  <th className="pb-2.5 text-right font-normal">Koers</th><th className="pb-2.5 text-right font-normal">Waarde</th>
                  <th className="pb-2.5 text-right font-normal">Ongerealiseerd</th><th className="pb-2.5 text-right font-normal">%</th>
                  <th className="pb-2.5 pl-4 font-normal">Strategie</th></tr></thead>
                <tbody>
                  {data.positions.map((x) => (
                    <tr key={x.desk + x.symbol} className="border-t border-white/[.04] transition-colors hover:bg-white/[.015]">
                      <td className="px-1 py-2.5 font-medium text-slate-100">{x.symbol}</td>
                      <td className="py-2.5"><span className="inline-flex items-center gap-1.5 text-slate-400"><span className="h-1.5 w-1.5 rounded-full" style={{ background: DESK_COLORS[x.desk] }} />{x.desk}</span></td>
                      <td className="num py-2.5 text-right text-slate-300"><span className="mr-2 align-middle"><DataBadge label={x.price_label} /></span>{eur(x.price_eur, x.price_eur != null && x.price_eur < 1 ? 6 : 2)}</td>
                      <td className="num py-2.5 text-right text-slate-100">{eur(x.value_eur)}</td>
                      <td className={`num py-2.5 text-right ${tone(x.unrealized_eur)}`}>{eur(x.unrealized_eur)}</td>
                      <td className={`num py-2.5 text-right ${tone(x.pnl_pct)}`}>{pct(x.pnl_pct, 1, true)}</td>
                      <td className="py-2.5 pl-4 font-mono text-[11.5px] text-slate-500">{x.strategy || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>Geen open posities.</Empty>}
        </Panel>
        <Panel title="Risicogebruik" action={<Link href="/risk" className="text-[12px] text-cyan-300 hover:text-cyan-200">Risk Guardian</Link>}>
          {data.risk.length ? (
            <ul className="space-y-3.5">
              {data.risk.map((r) => (
                <li key={r.key}>
                  <div className="mb-1.5 flex justify-between text-[12.5px]">
                    <span className={r.breached ? "text-rose-300" : "text-slate-300"}>{r.label}</span>
                    <span className="num text-slate-500">
                      {r.key === "positions" ? `${num(r.used, 0)} / ${num(r.limit, 0)}` : `${pct(r.used, 1)} / ${pct(r.limit, 0)}`}
                    </span>
                  </div>
                  <Meter value={r.utilization} />
                </li>
              ))}
            </ul>
          ) : <Empty>Zonder portefeuille geen risicometing.</Empty>}
        </Panel>
      </div>

      {/* 6 · Beslissingen, bevindingen, regime */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Panel title="Recente beslissingen" action={<Link href="/journal" className="text-[12px] text-cyan-300 hover:text-cyan-200">Journal</Link>}>
          {data.decisions.length ? (
            <ul className="space-y-3 text-[13px]">
              {data.decisions.slice(0, 6).map((d, i) => (
                <li key={i} className="flex gap-3">
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${d.kind === "trade" ? "bg-emerald-400" : "bg-rose-500"}`} title={d.kind === "trade" ? "uitgevoerd" : "afgewezen"} />
                  <div className="min-w-0"><div className="truncate text-slate-200" title={d.detail}>{d.text}</div>
                    <div className="truncate text-[11.5px] text-slate-500" title={d.detail}>{d.desk} · {ago(d.ts)} · {d.strategy}</div></div>
                </li>
              ))}
            </ul>
          ) : <Empty>Nog geen beslissingen.</Empty>}
        </Panel>
        <Panel title="Onderzoeksbevindingen" label={data.environment === "demo" ? "SIMULATED" : data.findings.length ? "DELAYED" : "UNAVAILABLE"}>
          {data.findings.length ? (
            <ul className="space-y-3 text-[13px]">
              {data.findings.slice(0, 5).map((f, i) => (
                <li key={i} className="flex gap-3">
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${f.level === "groot" ? "bg-rose-400" : f.kind === "reflection" ? "bg-violet-400" : "bg-amber-400"}`} />
                  <div><div className="text-slate-200">{f.text}</div><div className="text-[11.5px] text-slate-500">{f.desk} · {ago(f.ts)}</div></div>
                </li>
              ))}
            </ul>
          ) : <Empty>Geen bevindingen.</Empty>}
        </Panel>
        <Panel title="Marktregime" label={data.regime?.label ?? "UNAVAILABLE"}>
          {data.regime && (data.regime.weather.length || data.regime.risk_director) ? (
            <div className="space-y-3 text-[13px]">
              {data.regime.weather.map((w) => (
                <div key={w.name} className="flex gap-3">
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${w.ok ? "bg-emerald-400" : "bg-rose-500"}`} />
                  <div><div className="text-slate-200">{w.name}: {w.ok ? "risk-on" : "risk-off"}</div>
                    <div className="text-[11.5px] text-slate-500">{w.text}</div></div>
                </div>
              ))}
              {data.regime.risk_director && (
                <p className="border-t border-white/[.05] pt-3 text-[12px] leading-relaxed text-slate-400">
                  Risicodirecteur: beweeglijkheid crypto + memes <b className="num font-medium text-slate-200">{pct(data.regime.risk_director.vol, 1)}</b> per jaar
                  (doel {pct(data.regime.risk_director.target, 0)}), in de markt <b className="num font-medium text-slate-200">{pct(data.regime.risk_director.exposure, 1)}</b>
                  <span className="text-slate-600"> · {ago(data.regime.risk_director.computed_at)}</span>
                </p>
              )}
              {data.regime.vix != null && <div className="text-[12px] text-slate-500">VIX {num(data.regime.vix, 1)}</div>}
            </div>
          ) : <Empty>Nog geen regime: te weinig dagkoersen.</Empty>}
        </Panel>
      </div>

      <Panel title="Verbindingen">
        <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
          {data.connections.map((c) => (
            <div key={c.name} className="flex gap-2.5">
              <span className="mt-1.5"><StatusDot status={c.status} /></span>
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[13px] text-slate-200">{c.name}<DataBadge label={c.label} /></div>
                <div className="text-[11.5px] leading-snug text-slate-500">{c.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Fact({ k, v, c = "" }: { k: string; v: string; c?: string }) {
  return <div><dt className="caption">{k}</dt><dd className={`num mt-1 text-slate-100 ${c}`}>{v}</dd></div>;
}

function Loading() {
  return (
    <div className="space-y-5" aria-busy>
      <Skeleton className="h-12 w-72" />
      <Skeleton className="h-28" />
      <div className="grid gap-5 xl:grid-cols-[1fr_340px]"><Skeleton className="h-[440px]" /><Skeleton className="h-[440px]" /></div>
      <div className="grid gap-5 xl:grid-cols-[420px_1fr]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
    </div>
  );
}
