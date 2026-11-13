"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import { ago, eur, num, pct, time, tone } from "@/lib/format";
import type { CommandCenter as CC } from "@/lib/types";
import { EnvBanner } from "./Banner";
import { Delta, Freshness, KpiCell, KpiStrip, Provenance, Tabs } from "./ds";
import { EquityChart } from "./EquityChart";
import { KillSwitch } from "./KillSwitch";
import { DataBadge, Empty, ErrorBox, Meter, Panel, Skeleton, StatusDot } from "./ui";
import { useState } from "react";

/* Gedempte afdelingskleuren: metaal en ijsblauw, violet als tweede reeks. */
const DESK_COLORS: Record<string, string> = {
  crypto: "#8CCBF2", meme: "#A79BEA", stocks: "#B9C2CF", metals: "#DDB25C", fx: "#4CC495", cash: "#4A525F",
};
const MODE_TEXT = { research: "Research", paper: "Paper trading", live: "Live" } as const;

interface Task { id: number; kind: string; agent: string; status: string; subject: string | null; reason: string; created_at: string }
interface Prov { key: string; name: string; group: string; state: string }
interface Wf { id: number; trace_id: string; title: string; source: string; simulated: boolean; published_at: string; status: string;
  intelligence: { research_priority: string; assets: string[]; confirmed: string } }
interface Overview { as_of: string | null; label: "DELAYED" | "HISTORICAL" | "UNAVAILABLE"; vix: number | null; regime: { summary: string };
  classes: { asset_class: string; n: number; ret_1d: number; ret_7d: number; ret_30d: number; breadth_up_1d: number }[] }
interface Org { roles: { key: string; last_activity: string | null; open_tasks: unknown[] }[] }

const CLASS_NL: Record<string, string> = { crypto: "Crypto", meme: "Memecoins", stocks: "Aandelen", metals: "Metalen", fx: "Valuta", context: "Indices & rente" };
const STATE_ORDER = ["CONNECTED", "DEGRADED", "DISCONNECTED", "NOT CONFIGURED"] as const;
const STATE_DOT: Record<string, string> = { CONNECTED: "ok", DEGRADED: "degraded", DISCONNECTED: "down", "NOT CONFIGURED": "not_configured" };

/**
 * Executive Command Center 6.0. Volgorde volgt de vraag van de CEO:
 * 1. hoe staan we ervoor (kerncijfers, grote curve), 2. wat vraagt om mij (besluiten, besturing),
 * 3. wat gebeurt er (markt, onderzoek, nieuws), 4. waar zit het risico (posities, limieten), 5. wat werkt er (verbindingen).
 * Onderzoekskansen en goedgekeurde trades staan bewust in aparte kolommen.
 */
export function CommandCenter() {
  const { data, error, loading, refresh, updatedAt } = useApi<CC>("/api/command-center", 30_000);
  const esc = useApi<Task[]>("/api/central/tasks?status=escalated&limit=20", 60_000);
  const prov = useApi<{ providers: Prov[] }>("/api/providers", 120_000);
  const wfs = useApi<{ items: Wf[]; total: number }>("/api/workflows?limit=8", 60_000);
  const ov = useApi<Overview>("/api/market/overview", 300_000);
  const org = useApi<Org>("/api/central/org", 120_000);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  if (!data) return null;
  const p = data.portfolio;
  const worstRisk = data.risk.length ? data.risk.reduce((a, b) => (b.utilization > a.utilization ? b : a)) : null;
  const gatePassed = data.controls.live_gate.filter((g) => g.passed).length;
  const pending = (esc.data ?? []).length;
  const approved = data.proposals.filter((x) => x.verdict?.approved || x.executed);
  const research = (wfs.data?.items ?? []).filter((w) => w.intelligence?.research_priority && !w.intelligence.research_priority.startsWith("geen"));
  const day = (org.updatedAt?.getTime() ?? 0) - 86_400_000;   // ophaalmoment, geen klok tijdens renderen
  const activeRoles = (org.data?.roles ?? []).filter((r) => r.last_activity && new Date(r.last_activity).getTime() > day).length;
  const states = (prov.data?.providers ?? []).reduce<Record<string, number>>((m, x) => ({ ...m, [x.state]: (m[x.state] ?? 0) + 1 }), {});

  return (
    <div className="page-in space-y-5">
      <EnvBanner env={data.environment} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">JP-libau Holding · NEXUS</div>
          <h1 className="title-lg mt-1.5">Command Center</h1>
          <p className="t-label mt-1.5">
            Stand van {time(data.as_of ?? data.generated_at)}
            {updatedAt && <> · opgehaald {ago(updatedAt.toISOString())}</>}
            {error && <span className="text-amber-300"> · laatste verversing mislukt</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          <span className="chip">Modus <b className="font-medium text-slate-100">{MODE_TEXT[data.controls.mode]}</b></span>
          <span className="chip">Live handelen <b className="font-medium text-slate-100">uit</b></span>
          <Link href="/risk" className="chip hover:text-slate-200">Live-poort <b className="num font-medium text-slate-100">{gatePassed}/{data.controls.live_gate.length}</b></Link>
          <Link href="/hq" className={`chip ${pending ? "border-amber-300/30 text-amber-200" : ""}`}>Wacht op jou <b className="num font-medium">{pending}</b></Link>
        </div>
      </header>

      {/* 1 · Kerncijfers, elk soort resultaat apart benoemd */}
      {p ? (
        <KpiStrip cols="md:grid-cols-4 xl:grid-cols-8">
          <KpiCell wide label="Vermogen holding-bots" label2={p.label} value={eur(p.equity_eur, 0)}
            sub={`start ${eur(p.capital_eur, 0)} papiergeld · ${p.days_active} dagen`} />
          <KpiCell label="Resultaat sinds start" value={pct(p.pnl_pct, 2, true)} tone={tone(p.pnl_eur)} sub={`${eur(p.pnl_eur)} · paper`} />
          <KpiCell label="Gerealiseerd" value={eur(p.realized_eur)} tone={tone(p.realized_eur)} sub="gesloten posities" />
          <KpiCell label="Ongerealiseerd" value={eur(p.unrealized_eur)} tone={tone(p.unrealized_eur)} sub="open posities, vertraagde koers" />
          <KpiCell label="Vs. koop-en-houd" value={p.benchmark_eur != null ? eur(p.equity_eur - p.benchmark_eur) : "—"}
            tone={p.benchmark_eur != null ? tone(p.equity_eur - p.benchmark_eur) : ""} sub={p.benchmark_eur != null ? `benchmark ${eur(p.benchmark_eur, 0)}` : "geen benchmark"} />
          <KpiCell label="Drawdown" value={pct(-p.drawdown, 2)} tone={p.drawdown > 0 ? "text-rose-300" : ""} sub={`top ${eur(p.peak_eur, 0)}`} />
          <KpiCell label="Zwaarste limiet" href="/risk" value={worstRisk ? pct(worstRisk.utilization, 0) : "—"}
            tone={worstRisk && worstRisk.utilization >= 1 ? "text-rose-300" : worstRisk && worstRisk.utilization >= 0.7 ? "text-amber-200" : ""}
            sub={worstRisk ? worstRisk.label : "geen meting"} />
        </KpiStrip>
      ) : <Empty>Geen portefeuilledata. Er worden geen getallen verzonnen.</Empty>}

      {/* 2 · Grote curve + wat om een besluit vraagt */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel title="Vermogen en drawdown" label={p?.label ?? "UNAVAILABLE"}
          action={<span className="t-label">stippellijn = startkapitaal</span>}>
          {p ? (
            <>
              <EquityChart curve={p.equity_curve} capital={p.capital_eur} height={380} />
              <div className="mt-3 grid gap-3 border-t border-white/[.05] pt-3 text-[12px] sm:grid-cols-2 lg:grid-cols-4">
                <Legend k="Paper (deze curve)" v="holding-bots met papiergeld" tag={<DataBadge label="SIMULATED" />} />
                <Legend k="NEXUS paper-account" v={data.nexus_paper ? `${eur(data.nexus_paper.equity_eur)} · ${eur(data.nexus_paper.pnl_eur)}` : "—"} tag={<DataBadge label="SIMULATED" />} />
                <Legend k="Backtests" v={<Link href="/evolution" className="text-cyan-300 hover:text-cyan-200">Evolution Lab</Link>} tag={<span className="chip">niet in deze cijfers</span>} />
                <Legend k="Kosten totaal" v={eur(p.fees_eur)} tag={<Provenance kind="measured" />} />
              </div>
            </>
          ) : <Empty>Geen curve zonder data.</Empty>}
        </Panel>

        <div className="space-y-5">
          <Panel title="Wacht op jouw besluit" action={<Link href="/hq" className="text-[12px] text-cyan-300 hover:text-cyan-200">Alles</Link>}>
            {esc.data?.length ? (
              <ul className="space-y-2.5 text-[12.5px]">
                {esc.data.slice(0, 4).map((t) => (
                  <li key={t.id} className="flex gap-2.5"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-300" />
                    <div className="min-w-0"><div className="truncate text-slate-100" title={t.reason}>{t.reason}</div>
                      <div className="t-micro">{t.kind} · {t.agent} · {ago(t.created_at)}</div></div></li>
                ))}
              </ul>
            ) : <p className="text-[12.5px] text-slate-500">{esc.data ? "Niets wacht op jou." : "Laden…"}</p>}
          </Panel>
          <Panel title="Besturing">
            <KillSwitch status={data.controls.kill} onChange={refresh} />
            <p className="t-micro mt-3">Live handelen staat uit. Elke order gaat door de Risk Guardian; agenten kunnen geen limieten wijzigen.</p>
          </Panel>
          <Panel title="Verbindingen" action={<Link href="/operations" className="text-[12px] text-cyan-300 hover:text-cyan-200">Control Center</Link>}>
            {prov.data ? (
              <div className="space-y-2 text-[12.5px]">
                {STATE_ORDER.map((s) => (
                  <div key={s} className="flex items-center justify-between"><span className="flex items-center gap-2 font-mono text-[11.5px] text-slate-300"><StatusDot status={STATE_DOT[s]} />{s}</span>
                    <span className="num text-slate-200">{states[s] ?? 0}</span></div>
                ))}
                <p className="t-micro pt-1">Groen alleen na een echte, geslaagde test. Paper broker: SIMULATED.</p>
              </div>
            ) : <Skeleton className="h-28" />}
          </Panel>
        </div>
      </div>

      {/* 3 · Markt, onderzoek en goedgekeurde handel naast elkaar */}
      <div className="grid gap-5 lg:grid-cols-3">
        <Panel title="Marktomstandigheden" action={<Link href="/pulse" className="text-[12px] text-cyan-300 hover:text-cyan-200">Market Pulse</Link>}>
          {ov.data ? (
            <>
              <div className="mb-3"><Freshness label={ov.data.label} ts={ov.data.as_of} /></div>
              <table className="dtable">
                <thead><tr><th>Klasse</th><th className="r">1d</th><th className="r">7d</th><th className="r">30d</th></tr></thead>
                <tbody>
                  {ov.data.classes.map((c) => (
                    <tr key={c.asset_class}><td className="text-slate-200">{CLASS_NL[c.asset_class] ?? c.asset_class} <span className="t-micro">{c.n}</span></td>
                      <td className="r"><Delta v={c.ret_1d} /></td><td className="r"><Delta v={c.ret_7d} /></td><td className="r"><Delta v={c.ret_30d} /></td></tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-[12px] text-slate-400">{ov.data.regime.summary}</p>
            </>
          ) : <Skeleton className="h-48" />}
        </Panel>
        <Panel title="Onderzoekskansen" action={<span className="flex items-center gap-2"><span className="chip">geen handelsadvies</span></span>}>
          {research.length ? (
            <ul className="space-y-2.5 text-[12.5px]">
              {research.slice(0, 5).map((w) => (
                <li key={w.id}><Link href={`/decisions?trace=${w.id}`} className="line-clamp-2 text-slate-100 hover:text-white">{w.title}</Link>
                  <div className="t-micro mt-0.5 flex flex-wrap items-center gap-1.5">prioriteit {w.intelligence.research_priority} · {w.intelligence.assets.join(", ") || "geen instrument"} · {ago(w.published_at)}
                    {w.simulated && <DataBadge label="SIMULATED" />}</div></li>
              ))}
            </ul>
          ) : <Empty>Geen open onderzoekssporen. Zonder echte nieuwsfeeds ontstaan er geen nieuwe.</Empty>}
        </Panel>
        <Panel title="Goedgekeurde trades" action={<Link href="/execution" className="text-[12px] text-cyan-300 hover:text-cyan-200">Execution</Link>}>
          {approved.length ? (
            <ul className="space-y-2.5 text-[12.5px]">
              {approved.slice(0, 5).map((x) => (
                <li key={x.id} className="flex justify-between gap-2"><span className="text-slate-100">{x.direction} {x.symbol}</span>
                  <span className="t-micro">{x.executed ? "uitgevoerd (paper)" : "goedgekeurd"} · {ago(x.created_at)}</span></li>
              ))}
            </ul>
          ) : <Empty>Geen door de Risk Guardian goedgekeurde voorstellen. {data.proposals.length ? `${data.proposals.length} voorstellen, waarvan ${data.proposals.filter((x) => x.status === "vetoed").length} met veto.` : ""}</Empty>}
          <p className="t-micro mt-3">{data.fills_today ?? 0} paper-trades vandaag door de holding-bots.</p>
        </Panel>
      </div>

      {/* 4 · Risico en posities */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Positions data={data} />
        <Panel title="Risicogebruik" action={<Link href="/risk" className="text-[12px] text-cyan-300 hover:text-cyan-200">Risk Guardian</Link>}>
          {data.risk.length ? (
            <ul className="space-y-3.5">
              {data.risk.map((r) => (
                <li key={r.key}>
                  <div className="mb-1.5 flex justify-between text-[12.5px]">
                    <span className={r.breached ? "text-rose-300" : "text-slate-300"}>{r.label}</span>
                    <span className="num text-slate-500">{r.key === "positions" ? `${num(r.used, 0)} / ${num(r.limit, 0)}` : `${pct(r.used, 1)} / ${pct(r.limit, 0)}`}</span>
                  </div>
                  <Meter value={r.utilization} />
                </li>
              ))}
            </ul>
          ) : <Empty>Zonder portefeuille geen risicometing.</Empty>}
          {data.allocation.length > 0 && (
            <div className="mt-5 border-t border-white/[.05] pt-4">
              <div className="t-label mb-2">Verdeling</div>
              <div className="mb-3 flex h-1.5 gap-px overflow-hidden rounded-full">
                {data.allocation.map((a) => <div key={a.key} title={`${a.name} ${pct(a.pct, 1)}`} style={{ width: `${a.pct * 100}%`, background: DESK_COLORS[a.key] ?? "#6C7584" }} />)}
              </div>
              <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
                {data.allocation.map((a) => <li key={a.key} className="flex justify-between"><span className="flex items-center gap-1.5 text-slate-400"><span className="h-1.5 w-1.5 rounded-full" style={{ background: DESK_COLORS[a.key] ?? "#6C7584" }} />{a.name}</span><span className="num text-slate-300">{pct(a.pct, 0)}</span></li>)}
              </ul>
            </div>
          )}
        </Panel>
      </div>

      {/* 5 · AI-organisatie in één regel */}
      <Link href="/hq" className="panel flex flex-wrap items-center gap-x-8 gap-y-2 px-5 py-4 text-[12.5px] hover:border-white/[.12]">
        <span className="title-md">AI-organisatie</span>
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{activeRoles}</b> van {org.data?.roles.length ?? 19} rollen actief in 24 uur</span>
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{wfs.data?.total ?? 0}</b> gebeurtenis-sporen</span>
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{(org.data?.roles ?? []).reduce((n, r) => n + r.open_tasks.length, 0)}</b> open taken</span>
        <span className="ml-auto text-cyan-300">Neural Core en Decision Theater →</span>
      </Link>
    </div>
  );
}

function Positions({ data }: { data: CC }) {
  const [view, setView] = useState<"value" | "pnl">("value");
  const rows = [...data.positions].sort((a, b) => view === "value" ? b.value_eur - a.value_eur : (a.pnl_pct ?? 0) - (b.pnl_pct ?? 0));
  return (
    <Panel title={`Posities · ${data.positions.length}`} label={data.portfolio?.label ?? "UNAVAILABLE"}
      action={<Tabs label="Sortering" value={view} onChange={setView} items={[["value", "Grootste"], ["pnl", "Slechtste"]]} />}>
      {rows.length ? (
        <div className="-mx-2 overflow-x-auto">
          <table className="dtable min-w-[600px]">
            <thead><tr><th>Instrument</th><th>Afdeling</th><th className="r">Koers</th><th className="r">Waarde</th><th className="r">Ongerealiseerd</th><th className="r">%</th></tr></thead>
            <tbody>
              {rows.slice(0, 10).map((x) => (
                <tr key={x.desk + x.symbol}>
                  <td className="font-medium text-slate-100">{x.symbol}</td>
                  <td><span className="inline-flex items-center gap-1.5 text-slate-400"><span className="h-1.5 w-1.5 rounded-full" style={{ background: DESK_COLORS[x.desk] }} />{x.desk}</span></td>
                  <td className="r text-slate-300" title={x.price_ts ? `koers van ${new Date(x.price_ts).toLocaleString("nl-NL")}` : undefined}><span className="mr-2"><DataBadge label={x.price_label} /></span>{eur(x.price_eur, x.price_eur != null && x.price_eur < 1 ? 6 : 2)}</td>
                  <td className="r text-slate-100">{eur(x.value_eur)}</td>
                  <td className={`r ${tone(x.unrealized_eur)}`}>{eur(x.unrealized_eur)}</td>
                  <td className="r"><Delta v={x.pnl_pct} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 10 && <Link href="/portfolio" className="mt-2 inline-block px-2 text-[12px] text-cyan-300">Alle {rows.length} posities</Link>}
        </div>
      ) : <Empty>Geen open posities.</Empty>}
    </Panel>
  );
}

function Legend({ k, v, tag }: { k: string; v: React.ReactNode; tag?: React.ReactNode }) {
  return <div><div className="t-label flex items-center gap-2">{k}{tag}</div><div className="num mt-1 text-slate-200">{v}</div></div>;
}

function Loading() {
  return (
    <div className="space-y-5" aria-busy>
      <Skeleton className="h-12 w-72" />
      <Skeleton className="h-28" />
      <div className="grid gap-5 xl:grid-cols-[1fr_360px]"><Skeleton className="h-[480px]" /><Skeleton className="h-[480px]" /></div>
    </div>
  );
}
