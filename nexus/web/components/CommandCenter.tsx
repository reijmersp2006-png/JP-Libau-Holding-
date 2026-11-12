"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import { ago, eur, num, pct, time, tone } from "@/lib/format";
import type { CommandCenter as CC } from "@/lib/types";
import { EnvBanner } from "./Banner";
import { EquityChart, Spark } from "./EquityChart";
import { KillSwitch } from "./KillSwitch";
import { DataBadge, Empty, ErrorBox, Meter, Panel, Skeleton, Stat, StatusDot } from "./ui";

const DESK_COLORS: Record<string, string> = {
  crypto: "#22d3ee", meme: "#f472b6", stocks: "#a78bfa", metals: "#fbbf24", fx: "#34d399", cash: "#475569",
};
const MODE_TEXT = { research: "Research (alleen analyseren)", paper: "Paper trading (nepgeld)", live: "Live" } as const;

export function CommandCenter() {
  const { data, error, loading, refresh, updatedAt } = useApi<CC>("/api/command-center", 30_000);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  if (!data) return null;
  const p = data.portfolio;

  return (
    <div className="space-y-4">
      <EnvBanner env={data.environment} />
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Command Center</h1>
          <p className="text-sm text-slate-400">
            Stand van {time(data.as_of ?? data.generated_at)} · ververst elke 30 s
            {updatedAt && <> · opgehaald {ago(updatedAt.toISOString())}</>}
            {error && <span className="text-amber-300"> · laatste verversing mislukt</span>}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[11px] text-slate-500">
          {(["LIVE", "DELAYED", "HISTORICAL", "SIMULATED", "UNAVAILABLE"] as const).map((l) => <DataBadge key={l} label={l} />)}
        </div>
      </div>

      {/* Rij 1: vermogen + besturing */}
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Panel title="Totaal vermogen" label={p ? p.label : "UNAVAILABLE"} glow>
          {p ? (
            <div className="grid gap-5 md:grid-cols-[minmax(220px,auto)_1fr]">
              <div>
                <div className="num text-4xl font-semibold tracking-tight text-white md:text-5xl">{eur(p.equity_eur)}</div>
                <div className={`num mt-1 text-sm ${tone(p.pnl_eur)}`}>
                  {eur(p.pnl_eur)} ({pct(p.pnl_pct, 2, true)}) sinds start · {p.days_active} dagen
                </div>
                <div className="mt-1 text-xs text-slate-500">Startkapitaal {eur(p.capital_eur, 0)} nepgeld</div>
              </div>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                <Stat label="Gerealiseerd" value={eur(p.realized_eur)} valueClass={tone(p.realized_eur)} sub="na verkoopkosten" />
                <Stat label="Ongerealiseerd" value={eur(p.unrealized_eur)} valueClass={tone(p.unrealized_eur)} sub="open posities" />
                <Stat label="Aankoopkosten" value={eur(-p.buy_fees_eur)} valueClass="text-slate-300" sub={`totaal kosten ${eur(p.fees_eur)}`} />
                <Stat label="Vandaag" value={pct(p.day_pnl_pct, 2, true)} valueClass={tone(p.day_pnl_pct)} sub="t.o.v. 24 uur terug" />
                <Stat label="Drawdown" value={pct(-p.drawdown, 2)} valueClass={p.drawdown > 0 ? "text-rose-400" : "text-slate-300"} sub={`top ${eur(p.peak_eur)}`} />
                <Stat label="Koop-en-houd" value={eur(p.benchmark_eur)} sub={p.benchmark_eur != null ? `verschil ${eur(p.equity_eur - p.benchmark_eur)}` : "geen maatlat"} />
              </div>
            </div>
          ) : <Empty>Geen portefeuilledata. Er worden geen getallen verzonnen.</Empty>}
        </Panel>

        <Panel title="Handelsstatus">
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Modus</span>
              <span className="font-medium text-cyan-200">{MODE_TEXT[data.controls.mode]}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Live handelen</span>
              <span className="rounded-md border border-slate-600 px-2 py-0.5 font-mono text-xs text-slate-300">UITGESCHAKELD</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Live-poort</span>
              <Link href="/risk" className="text-xs text-slate-400 underline decoration-slate-700 underline-offset-4 hover:text-cyan-200">
                {data.controls.live_gate.filter((g) => g.passed).length} van {data.controls.live_gate.length} checks
              </Link>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Paper-trades vandaag</span>
              <span className="num">{data.fills_today ?? "—"}</span>
            </div>
            <KillSwitch status={data.controls.kill} onChange={refresh} />
          </div>
        </Panel>
      </div>

      {/* Rij 2: curve + verdeling */}
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Panel title="Vermogen en drawdown" label={p?.label ?? "UNAVAILABLE"}
          action={<span className="text-[11px] text-slate-500">stippellijn = startkapitaal</span>}>
          {p ? <EquityChart curve={p.equity_curve} capital={p.capital_eur} /> : <Empty>Geen curve zonder data.</Empty>}
        </Panel>
        <Panel title="Verdeling" label={p?.label ?? "UNAVAILABLE"}>
          {data.allocation.length ? (
            <>
              <div className="mb-4 flex h-3 overflow-hidden rounded-full bg-slate-800">
                {data.allocation.map((a) => (
                  <div key={a.key} title={`${a.name} ${pct(a.pct, 1)}`} style={{ width: `${a.pct * 100}%`, background: DESK_COLORS[a.key] ?? "#64748b" }} />
                ))}
              </div>
              <ul className="space-y-2">
                {data.allocation.map((a) => (
                  <li key={a.key} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: DESK_COLORS[a.key] ?? "#64748b" }} />{a.name}</span>
                    <span className="num text-slate-300">{eur(a.value_eur)} <span className="ml-1 text-slate-500">{pct(a.pct, 1)}</span></span>
                  </li>
                ))}
              </ul>
            </>
          ) : <Empty>Geen posities.</Empty>}
        </Panel>
      </div>

      {/* Rij 3: risico, regime, agents */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Risicogebruik" action={<Link href="/risk" className="text-[11px] text-cyan-300/80 hover:text-cyan-200">Risk Guardian →</Link>}>
          {data.risk.length ? (
            <ul className="space-y-3">
              {data.risk.map((r) => (
                <li key={r.key}>
                  <div className="mb-1 flex justify-between text-xs">
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

        <Panel title="Marktregime" label={data.regime?.label ?? "UNAVAILABLE"}>
          {data.regime && (data.regime.weather.length || data.regime.risk_director) ? (
            <div className="space-y-3 text-sm">
              {data.regime.weather.map((w) => (
                <div key={w.name} className="flex gap-2.5">
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${w.ok ? "bg-emerald-400" : "bg-rose-500"}`} />
                  <div><div className="font-medium text-slate-200">{w.name}: {w.ok ? "risk-on" : "risk-off"}</div>
                    <div className="text-xs text-slate-500">{w.text}</div></div>
                </div>
              ))}
              {data.regime.risk_director && (
                <div className="rounded-lg border border-white/5 bg-white/[.02] p-2.5 text-xs text-slate-400">
                  Risicodirecteur: beweeglijkheid crypto + memes <b className="num text-slate-200">{pct(data.regime.risk_director.vol, 1)}</b> per jaar
                  (doel {pct(data.regime.risk_director.target, 0)}), in de markt <b className="num text-slate-200">{pct(data.regime.risk_director.exposure, 1)}</b>.
                  <span className="block text-slate-600">berekend {ago(data.regime.risk_director.computed_at)}</span>
                </div>
              )}
              {data.regime.vix != null && <div className="text-xs text-slate-500">VIX {num(data.regime.vix, 1)}</div>}
            </div>
          ) : <Empty>Nog geen regime: te weinig dagkoersen.</Empty>}
        </Panel>

        <Panel title="AI Expert Council" action={<Link href="/council" className="text-[11px] text-cyan-300/80 hover:text-cyan-200">Alle 13 →</Link>}>
          <div className="mb-3 grid grid-cols-3 gap-2 text-center">
            {([["operational", "draait", "text-emerald-300"], ["partial", "deels", "text-amber-300"], ["not_built", "nog niet", "text-slate-400"]] as const).map(([k, l, c]) => (
              <div key={k} className="rounded-lg border border-white/5 bg-white/[.02] py-2">
                <div className={`num text-xl font-semibold ${c}`}>{data.agents.summary[k] ?? 0}</div>
                <div className="text-[10.5px] text-slate-500">{l}</div>
              </div>
            ))}
          </div>
          <ul className="space-y-1.5 text-xs">
            {data.agents.items.filter((a) => a.status !== "not_built").slice(0, 6).map((a) => (
              <li key={a.id} className="flex items-center justify-between">
                <span className="flex items-center gap-2"><StatusDot status={a.status === "operational" ? "ok" : "degraded"} />{a.name}</span>
                <span className="text-slate-500">{a.last_activity ? ago(a.last_activity) : "—"}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] text-slate-600">Geen enkele rol draait nog op een taalmodel. LLM-analyses volgen in fase 3.</p>
        </Panel>
      </div>

      {/* Rij 4: posities + voorstellen/bevindingen */}
      <div className="grid gap-4 xl:grid-cols-[1fr_400px]">
        <Panel title={`Actieve posities (${data.positions.length})`} label={p?.label ?? "UNAVAILABLE"}>
          {data.positions.length ? (
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                  <th className="px-1 pb-2 font-medium">Instrument</th><th className="pb-2 font-medium">Afdeling</th>
                  <th className="pb-2 text-right font-medium">Koers</th><th className="pb-2 text-right font-medium">Waarde</th>
                  <th className="pb-2 text-right font-medium">Ongereal.</th><th className="pb-2 text-right font-medium">%</th>
                  <th className="pb-2 pl-3 font-medium">Strategie</th></tr></thead>
                <tbody>
                  {data.positions.map((x) => (
                    <tr key={x.desk + x.symbol} className="border-t border-white/[.04] hover:bg-white/[.02]">
                      <td className="px-1 py-2 font-medium text-slate-100">{x.symbol}</td>
                      <td className="py-2"><span className="inline-flex items-center gap-1.5 text-slate-400"><span className="h-2 w-2 rounded-sm" style={{ background: DESK_COLORS[x.desk] }} />{x.desk}</span></td>
                      <td className="num py-2 text-right text-slate-300"><span className="mr-1.5 align-middle"><DataBadge label={x.price_label} /></span>{eur(x.price_eur, x.price_eur != null && x.price_eur < 1 ? 6 : 2)}</td>
                      <td className="num py-2 text-right">{eur(x.value_eur)}</td>
                      <td className={`num py-2 text-right ${tone(x.unrealized_eur)}`}>{eur(x.unrealized_eur)}</td>
                      <td className={`num py-2 text-right ${tone(x.pnl_pct)}`}>{pct(x.pnl_pct, 1, true)}</td>
                      <td className="py-2 pl-3 font-mono text-[11px] text-slate-500">{x.strategy || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>Geen open posities.</Empty>}
        </Panel>

        <div className="space-y-4">
          <Panel title="Handelsvoorstellen" action={<span className="text-[11px] text-slate-500">via Risk Guardian</span>}>
            {data.proposals.length ? (
              <ul className="space-y-2 text-sm">
                {data.proposals.slice(0, 5).map((pr) => (
                  <li key={pr.id} className="flex items-center justify-between rounded-lg border border-white/5 px-2.5 py-1.5">
                    <span><b className="text-slate-100">{pr.symbol}</b> <span className="text-slate-500">{pr.direction} · {pr.strategy_id}</span></span>
                    <span className={`text-xs font-medium ${pr.status === "vetoed" ? "text-rose-300" : "text-emerald-300"}`}>{pr.status === "vetoed" ? "veto" : "goedgekeurd"}</span>
                  </li>
                ))}
              </ul>
            ) : <Empty>Geen voorstellen. De AI-agents die voorstellen maken komen in fase 3; tot dan is &ldquo;geen trade&rdquo; het antwoord.</Empty>}
          </Panel>
          <Panel title="Onderzoeksbevindingen" label={data.environment === "demo" ? "SIMULATED" : data.findings.length ? "DELAYED" : "UNAVAILABLE"}>
            {data.findings.length ? (
              <ul className="space-y-2.5 text-sm">
                {data.findings.slice(0, 5).map((f, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${f.level === "groot" ? "bg-rose-400" : f.kind === "reflection" ? "bg-violet-400" : "bg-amber-400"}`} />
                    <div><div className="text-slate-200">{f.text}</div><div className="text-[11px] text-slate-500">{f.desk} · {ago(f.ts)}</div></div>
                  </li>
                ))}
              </ul>
            ) : <Empty>Geen bevindingen.</Empty>}
          </Panel>
        </div>
      </div>

      {/* Rij 5: markten + beslissingen */}
      <div className="grid gap-4 xl:grid-cols-[1fr_400px]">
        <Panel title="Markten" action={<Link href="/radar" className="text-[11px] text-cyan-300/80 hover:text-cyan-200">Market Radar →</Link>}>
          {data.market.length ? (
            <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
              {data.market.map((q) => (
                <div key={q.symbol} className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[.015] px-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5"><span className="truncate text-sm font-medium text-slate-100">{q.name}</span><DataBadge label={q.label} /></div>
                    <div className="num whitespace-nowrap text-xs text-slate-400">{q.price == null ? "—" : `${q.currency} ${num(q.price, q.price < 1 ? 6 : 2)}`}
                      <span className={`ml-1.5 ${tone(q.change)}`}>{pct(q.change, 2, true)}</span></div>
                  </div>
                  <Spark values={q.line} up={(q.change ?? 0) >= 0} />
                </div>
              ))}
            </div>
          ) : <Empty>Geen marktdata.</Empty>}
        </Panel>
        <Panel title="Recente beslissingen" label={p?.label ?? "UNAVAILABLE"} action={<Link href="/journal" className="text-[11px] text-cyan-300/80 hover:text-cyan-200">Journal →</Link>}>
          {data.decisions.length ? (
            <ul className="space-y-2.5 text-sm">
              {data.decisions.slice(0, 7).map((d, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className={`mt-1 rounded px-1 font-mono text-[9.5px] font-bold ${d.kind === "trade" ? "bg-emerald-400/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"}`}>{d.kind === "trade" ? "OK" : "NEE"}</span>
                  <div className="min-w-0"><div className="truncate text-slate-200" title={d.detail}>{d.text}</div>
                    <div className="truncate text-[11px] text-slate-500" title={d.detail}>{d.desk} · {ago(d.ts)} · {d.strategy}</div></div>
                </li>
              ))}
            </ul>
          ) : <Empty>Nog geen beslissingen.</Empty>}
        </Panel>
      </div>

      <Panel title="Verbindingen">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {data.connections.map((c) => (
            <div key={c.name} className="flex gap-2.5 rounded-lg border border-white/5 bg-white/[.015] p-2.5">
              <span className="mt-1.5"><StatusDot status={c.status} /></span>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 text-sm font-medium text-slate-200">{c.name}<DataBadge label={c.label} /></div>
                <div className="text-[11px] leading-snug text-slate-500">{c.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Loading() {
  return (
    <div className="space-y-4" aria-busy>
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]"><Skeleton className="h-40" /><Skeleton className="h-40" /></div>
      <Skeleton className="h-80" />
      <div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-56" /><Skeleton className="h-56" /><Skeleton className="h-56" /></div>
    </div>
  );
}
