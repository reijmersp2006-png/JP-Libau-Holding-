"use client";

import { useState, type ReactNode } from "react";
import { Empty, ErrorBox, PageTitle, Panel, Skeleton, Stat } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, num, pct, time, tone } from "@/lib/format";

/* Evolution Lab. Elk getal draagt een soort:
   ACTUEEL = echte paper-uitkomsten en echte koersen; GESIMULEERD = backtest of herhaling;
   SCHATTING = onderzoeksuitkomst met onzekerheid. Live handelen staat uit en is hier niet te bedienen. */

type Kind = "actual" | "simulated" | "estimate";
const KIND: Record<Kind, { t: string; c: string; help: string }> = {
  actual: { t: "ACTUEEL", c: "text-emerald-300 border-emerald-400/40 bg-emerald-400/10", help: "Echte paper-uitkomsten en echte koersen" },
  simulated: { t: "GESIMULEERD", c: "text-violet-300 border-violet-400/30 bg-violet-400/10", help: "Backtest of historische herhaling" },
  estimate: { t: "SCHATTING", c: "text-amber-300 border-amber-400/30 bg-amber-400/10", help: "Onderzoeksschatting met onzekerheid" },
};
function K({ k }: { k: Kind }) {
  return <span title={KIND[k].help} className={`rounded-md border px-1.5 py-0.5 font-mono text-[9.5px] font-semibold tracking-wider ${KIND[k].c}`}>{KIND[k].t}</span>;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;

const TABS = [
  ["discovery", "Alpha Discovery"], ["learning", "Learning Progress"], ["council", "Agent Council"],
  ["arena", "Strategy Arena"], ["news", "News Intelligence"], ["memory", "Trade Memory"],
  ["models", "Model Registry"], ["external", "External Benchmark"],
] as const;
type Tab = (typeof TABS)[number][0];

function Loader<T>({ path, refresh = 60_000, children }: { path: string; refresh?: number; children: (d: T, reload: () => void) => ReactNode }) {
  const { data, error, loading, refresh: reload } = useApi<T>(path, refresh);
  if (loading && !data) return <Skeleton className="h-64" />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  return <>{children(data as T, reload)}</>;
}

function useAdmin() {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  async function post(path: string, body?: unknown, done?: () => void) {
    setBusy(path); setMsg(null);
    try {
      const r = await api<Any>(path, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: body ? JSON.stringify(body) : undefined });
      setMsg(r?.status ? `Klaar: ${r.status}` : "Klaar");
      done?.();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  }
  const field = (
    <div className="flex items-center gap-2">
      <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="admin-token"
        aria-label="Admin-token" className="w-40 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs" />
      {msg && <span className="max-w-xs truncate text-xs text-slate-400" title={msg}>{msg}</span>}
    </div>
  );
  return { token, busy, post, field };
}

function Btn({ onClick, disabled, children }: { onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return <button onClick={onClick} disabled={disabled} className="rounded-md border border-slate-600 px-2.5 py-1 text-xs hover:border-cyan-400/60 disabled:opacity-40">{children}</button>;
}

const p0 = (v: number | null | undefined) => pct(v, 0);
const sh = (v: number | null | undefined) => num(v, 2);

export default function Page() {
  const [tab, setTab] = useState<Tab>("discovery");
  const admin = useAdmin();
  return (
    <>
      <PageTitle title="Evolution Lab"
        sub="Het onderzoeks- en leersysteem. Elke strategie moet koop-en-houd na kosten verslaan op data die bij het afstemmen niet gezien is. Lukt dat niet, dan staat dat hier. Leren verandert nooit zelf live handelen of risicolimieten."
        right={<div className="flex flex-col items-end gap-2">
          <span className="rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-300">Live handelen: UIT</span>
          <div className="flex gap-1.5"><K k="actual" /><K k="simulated" /><K k="estimate" /></div>
        </div>} />
      <nav className="mb-4 flex flex-wrap gap-1" role="tablist">
        {TABS.map(([k, t]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-md border px-3 py-1.5 text-xs ${tab === k ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-100" : "border-slate-700 text-slate-400 hover:text-slate-200"}`}>{t}</button>
        ))}
        <div className="ml-auto">{admin.field}</div>
      </nav>
      {tab === "discovery" && <Discovery admin={admin} />}
      {tab === "learning" && <Learning admin={admin} />}
      {tab === "council" && <Council admin={admin} />}
      {tab === "arena" && <Arena />}
      {tab === "news" && <News admin={admin} />}
      {tab === "memory" && <Memory />}
      {tab === "models" && <Models admin={admin} />}
      {tab === "external" && <External admin={admin} />}
    </>
  );
}

type Admin = ReturnType<typeof useAdmin>;

function Discovery({ admin }: { admin: Admin }) {
  return (
    <Loader<Any> path="/api/evolution/discovery">{(d, reload) => (
      <div className="grid gap-4">
        <Panel title="Laatste ontdekkingsrun" action={<Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/evolution/discovery", undefined, reload)}>Nieuwe run (zwaar)</Btn>}>
          {!d.available ? <Empty>Nog geen ontdekkingsrun in deze database. Draai er een, of gebruik <code>nexus-research discover</code>.</Empty> : (
            <>
              <div className="mb-3 flex items-center gap-2 text-xs text-slate-500"><K k="estimate" /> {time(d.created_at)} · interval {d.interval}</div>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
                <Stat label="Combinaties" value={d.summary.combinations} />
                <Stat label="Pogingen totaal" value={d.summary.trials_total} sub="telt mee in gedefleerde Sharpe" />
                <Stat label="Na ontwikkelpoorten" value={d.summary.candidates} />
                <Stat label="Geslaagd op holdout" value={d.summary.holdout_passed} valueClass={d.summary.holdout_passed ? "text-emerald-400" : ""} />
                <Stat label="Te weinig data" value={d.summary.insufficient_history} />
              </div>
              {d.summary.holdout_passed === 0 && <p className="mt-3 text-sm text-amber-200/90">Geen enkele combinatie versloeg koop-en-houd geloofwaardig. Dat is de eerlijke uitkomst van deze run.</p>}
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-slate-500"><tr><th className="py-1">Familie</th><th>Instrument(en)</th><th>Sharpe WF</th><th>Koop-en-houd</th><th>Max daling</th><th>P(beter)</th><th>Status</th><th>Waarom niet</th></tr></thead>
                  <tbody>{[...d.results].filter((r: Any) => r.walk_forward).sort((a: Any, b: Any) => (b.walk_forward.sharpe - b.benchmark.sharpe) - (a.walk_forward.sharpe - a.benchmark.sharpe)).slice(0, 40).map((r: Any, i: number) => (
                    <tr key={i} className="border-t border-white/5 align-top">
                      <td className="py-1 text-slate-200">{r.family_name ?? r.family}</td><td className="font-mono">{r.symbols.join(", ")}</td>
                      <td className="num">{sh(r.walk_forward.sharpe)}</td><td className="num">{sh(r.benchmark.sharpe)}</td>
                      <td className="num">{p0(r.walk_forward.max_drawdown)}</td><td className="num">{p0(r.uncertainty?.p_sharpe_better)}</td>
                      <td>{r.status}</td><td className="max-w-md text-slate-500">{(r.reasons ?? []).slice(0, 2).join("; ")}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            </>
          )}
        </Panel>
        <Panel title="Strategiefamilies">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{d.families.map((f: Any) => (
            <div key={f.key} className="rounded-lg border border-white/5 p-3">
              <div className="flex justify-between"><span className="font-medium text-slate-100">{f.name}</span><span className="text-[11px] text-slate-500">{f.group}</span></div>
              <p className="mt-1 text-xs text-slate-400">{f.hypothesis}</p>
              <div className="mt-1 text-[11px] text-slate-500">{f.kind === "unavailable" ? `Niet beschikbaar: ${f.unavailable_reason}` : `${f.trials} instellingen · ${f.asset_classes.join(", ")}`}</div>
            </div>))}</div>
        </Panel>
      </div>
    )}</Loader>
  );
}

function Learning({ admin }: { admin: Admin }) {
  return (
    <div className="grid gap-4">
      <Loader<Any> path="/api/evolution/overview">{(o, reload) => (
        <Panel title="Leerlus" action={<Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/evolution/cycle", undefined, reload)}>Leerronde starten</Btn>}>
          <ol className="mb-3 flex flex-wrap gap-1 text-[11px] text-slate-400">{["Observeren", "Besluiten", "Uitvoeren / afwijzen", "Meten", "Analyseren", "Leren", "Valideren", "Verbeteren"].map((s, i) => <li key={s}>{i > 0 && "→ "}{s}</li>)}</ol>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Besluiten vastgelegd" value={o.counts.decisions} sub={`${o.counts.decisions_measured} afgerekend`} />
            <Stat label="Hypothesen open" value={o.counts.hypotheses.open} sub={`${o.counts.hypotheses.supported} gesteund · ${o.counts.hypotheses.rejected} verworpen · ${o.counts.hypotheses.inconclusive} onbeslist`} />
            <Stat label="Kandidaat-modellen" value={o.counts.models.candidate} sub={`${o.counts.models.paper} op paper · ${o.counts.models.champion} kampioen`} />
            <Stat label="Live handelen" value="uit" />
          </div>
          <h3 className="eyebrow mt-4 mb-2">Geplande taken</h3>
          <table className="w-full text-xs"><tbody>{o.jobs.map((j: Any) => (
            <tr key={j.job} className="border-t border-white/5"><td className="py-1 font-mono">{j.job}</td><td className="text-slate-500">{j.cadence}</td><td className="text-slate-400">{j.description}</td>
              <td>{j.last_status ?? "nooit"}</td><td className="text-slate-500">{ago(j.last_started)}</td>
              <td><Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post(`/api/jobs/${j.job}/run`, undefined, reload)}>Nu</Btn></td></tr>))}</tbody></table>
        </Panel>
      )}</Loader>
      <Loader<Any[]> path="/api/evolution/hypotheses">{(hs) => (
        <Panel title="Hypothesen uit fouten en de audit">
          {hs.length === 0 ? <Empty>Nog geen hypothesen. Een leerronde maakt ze uit herhaalde foutpatronen en uit de IWDA-diagnose.</Empty> : (
            <div className="grid gap-2">{hs.map((h) => (
              <div key={h.id} className="rounded-lg border border-white/5 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium text-slate-100">#{h.id} {h.title}</span>
                  <span className="flex items-center gap-2 text-xs"><K k="estimate" />{h.status}</span></div>
                <p className="mt-1 text-xs text-slate-400">{h.statement}</p>
                {h.result?.candidates?.length > 0 && (
                  <table className="mt-2 w-full text-[11px]"><thead className="text-left text-slate-500"><tr><th>Kandidaat</th><th>Sharpe</th><th>Bron</th><th>Koop-en-houd</th><th>P(beter dan bron)</th><th>P(beter dan K&amp;H)</th></tr></thead>
                    <tbody>{h.result.candidates.map((c: Any) => <tr key={c.family}><td>{c.family}</td><td className="num">{sh(c.sharpe)}</td><td className="num">{sh(c.baseline_sharpe)}</td><td className="num">{sh(c.buy_hold_sharpe)}</td><td className="num">{p0(c.p_vs_baseline)}</td><td className="num">{p0(c.p_vs_buy_hold)}</td></tr>)}</tbody></table>)}
                {h.result?.reason && <p className="mt-1 text-xs text-slate-500">{h.result.reason}</p>}
              </div>))}</div>)}
        </Panel>
      )}</Loader>
    </div>
  );
}

function Council({ admin }: { admin: Admin }) {
  const [sym, setSym] = useState("IWDA.AS");
  return (
    <div className="grid gap-4">
      <Loader<Any> path="/api/council/agents">{(d, reload) => (
        <>
          <Panel title="AI Expert Council" action={<div className="flex gap-2">
            <input value={sym} onChange={(e) => setSym(e.target.value)} aria-label="Instrument" className="w-28 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs" />
            <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/council/run", { symbol: sym }, reload)}>Council bijeenroepen</Btn></div>}>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Stat label="Model" value={<span className="font-mono text-sm">{d.model}</span>} sub={d.key_present ? "sleutel aanwezig" : "geen sleutel: Council niet beschikbaar"} />
              <Stat label="Vandaag besteed" value={`$${num(d.spent_today_usd, 2)}`} sub={`dagbudget $${num(d.daily_budget_usd, 2)}`} />
              <Stat label="Groepsdenken" value={d.combinations.mean_agreement == null ? "—" : p0(d.combinations.mean_agreement)} sub="gemiddelde overeenstemming" />
              <Stat label="Runs" value={d.combinations.runs} />
            </div>
            <p className="mt-3 text-xs text-slate-500">Agents oordelen eerst los, daarna in debat. De CIO besluit zonder meerderheid: gewichten komen uit de trackrecord (Brier), krimpend bij weinig data. Een veto van de Risk Guardian betekent geen trade. Geen agent kan een order plaatsen.</p>
          </Panel>
          <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">{d.agents.map((a: Any) => {
            const s = d.scorecard.find((x: Any) => x.agent === a.key);
            return (
              <Panel key={a.key}>
                <div className="flex justify-between"><h3 className="font-semibold text-slate-100">{a.name}</h3><span className="text-[11px] text-slate-500">{a.kind === "llm" ? "Claude" : "regels"}</span></div>
                <p className="mt-1 text-xs text-slate-400">{a.responsibilities}</p>
                <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                  <div><div className="text-slate-500">gewicht</div><div className="num">{num(a.weight?.weight, 2)}</div></div>
                  <div><div className="text-slate-500">afgerekend</div><div className="num">{s?.forecasts ?? 0}</div></div>
                  <div><div className="text-slate-500">Brier</div><div className="num">{num(s?.brier, 3)}</div></div>
                </div>
                {!a.weight?.calibrated && <div className="mt-1 text-[11px] text-slate-600">nog niet gekalibreerd (minder dan 30 afgerekende voorspellingen)</div>}
                <div className="mt-1 text-[11px] text-slate-600">Grenzen: {a.limitations}</div>
              </Panel>);
          })}</div>
        </>
      )}</Loader>
      <Loader<Any[]> path="/api/council/runs">{(runs) => (
        <Panel title="Laatste besluiten">
          {runs.length === 0 ? <Empty>Nog geen Council-runs.</Empty> : runs.map((r) => (
            <div key={r.id} className="border-t border-white/5 py-2 text-sm first:border-0">
              <div className="flex flex-wrap justify-between gap-2"><span className="font-mono">{r.symbol}</span><span className="text-xs text-slate-500">{time(r.created_at)} · {r.status} · ${num(r.cost_usd, 3)}</span></div>
              {r.status === "done" ? <>
                <div className="mt-1"><K k="estimate" /> <b>{r.decision.action}</b> · omvang {p0(r.decision.size_fraction)} van het maximum</div>
                <p className="mt-1 text-xs text-slate-400">{r.decision.rationale}</p>
                {r.decision.disagreements?.length > 0 && <p className="mt-1 text-xs text-slate-500">Onenigheid: {r.decision.disagreements.join(" · ")}</p>}
              </> : <p className="text-xs text-slate-500">{r.error}</p>}
            </div>))}
        </Panel>
      )}</Loader>
    </div>
  );
}

function Gate({ s }: { s: string }) {
  const c = { pass: "text-emerald-300", fail: "text-rose-300", locked: "text-slate-500", pending: "text-amber-300" }[s] ?? "text-slate-400";
  return <span className={`font-mono text-[11px] ${c}`}>{s}</span>;
}

function Arena() {
  return (
    <Loader<Any> path="/api/evolution/arena?symbol=IWDA.AS" refresh={600_000}>{(a) => a.status === "insufficient_history" ? <Empty>Te weinig koersgeschiedenis voor de arena ({a.bars} dagen).</Empty> : (
      <div className="grid gap-4">
        <Panel title={`Champion-challenger · ${a.symbol}`}>
          <div className="mb-2 flex items-center gap-2 text-xs text-slate-500"><K k="simulated" /> walk-forward {a.split.test_start.slice(0, 10)} tot {a.split.holdout_start.slice(0, 10)} · holdout vanaf {a.split.holdout_start.slice(0, 10)} blijft dicht tot poorten 1, 2, 4, 5 en 6 gehaald zijn</div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label={`Kampioen: ${a.champion.key} v${a.champion.version}`} value={sh(a.champion.walk_forward.sharpe)} sub={`rendement ${pct(a.champion.walk_forward.net_return, 1, true)}`} />
            <Stat label="Koop-en-houd" value={sh(a.buy_hold.sharpe)} sub={`rendement ${pct(a.buy_hold.net_return, 1, true)} · daling ${p0(a.buy_hold.max_drawdown)}`} />
            <Stat label="Uitdagers" value={a.challengers.length} sub={`${a.trials} instellingen getest`} />
            <Stat label="Door ontwikkelpoorten" value={a.passed_dev_gates.length} sub={a.passed_dev_gates.join(", ") || "geen"} />
          </div>
        </Panel>
        <Panel title="Poorten per uitdager">
          <div className="overflow-x-auto"><table className="w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th className="py-1">Uitdager</th><th>Sharpe</th><th>Rendement</th><th>Daling</th><th>P(&gt; kampioen)</th><th>P(&gt; K&amp;H)</th>{["1", "2", "3", "4", "5", "6", "7", "8"].map((g) => <th key={g}>{g}</th>)}</tr></thead>
            <tbody>{a.challengers.map((c: Any) => (
              <tr key={c.family} className="border-t border-white/5"><td className="py-1 text-slate-200">{c.name}</td><td className="num">{sh(c.walk_forward.sharpe)}</td>
                <td className={`num ${tone(c.walk_forward.net_return)}`}>{pct(c.walk_forward.net_return, 1, true)}</td><td className="num">{p0(c.walk_forward.max_drawdown)}</td>
                <td className="num">{p0(c.vs_champion.p_sharpe_better)}</td><td className="num">{p0(c.vs_buy_hold.p_sharpe_better)}</td>
                {Object.entries(c.gates).map(([k, g]: [string, Any]) => <td key={k} title={`${k}: ${g.threshold ?? ""} ${g.note ?? ""}`}><Gate s={g.status} /></td>)}</tr>))}</tbody>
          </table></div>
          <p className="mt-2 text-[11px] text-slate-500">1 backtest · 2 walk-forward · 3 holdout · 4 dubbele kosten · 5 gevoeligheid · 6 Monte Carlo · 7 paper ≥ 30 dagen · 8 risicotoets en menselijke goedkeuring.</p>
        </Panel>
      </div>
    )}</Loader>
  );
}

function News({ admin }: { admin: Admin }) {
  return (
    <Loader<Any> path="/api/news">{(d, reload) => (
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Panel title="Nieuws uit officiële bronnen" action={<Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/news/ingest", undefined, reload)}>Ophalen</Btn>}>
          {d.items.length === 0 ? <Empty>Nog geen nieuws opgehaald. Bronnen: {d.feeds.map((f: Any) => f.name).join(", ")}.</Empty> : d.items.map((n: Any) => (
            <div key={n.id} className="border-t border-white/5 py-2 first:border-0">
              <div className="flex justify-between gap-2 text-[11px] text-slate-500"><span>{n.source} · {n.category} · {n.factuality === "fact" ? "feit" : n.factuality === "mixed" ? "feit + vooruitblik" : "speculatie"}</span><span>{time(n.published_at)}</span></div>
              <a href={n.url} target="_blank" rel="noreferrer" className="text-sm text-slate-200 hover:text-cyan-200">{n.title}</a>
              {n.reaction && Object.keys(n.reaction).length > 0 && <div className="mt-1 flex flex-wrap gap-2 text-[11px]"><K k="actual" />{Object.entries(n.reaction).map(([s, r]: [string, Any]) => <span key={s} className="font-mono">{s} 1d {r.d1 ? `${pct(r.d1.return, 2, true)} (${num(r.d1.z, 1)}σ)` : "—"}</span>)}</div>}
              <div className="mt-0.5 text-[11px] text-slate-600">Verwachting: {n.expectation?.available ? JSON.stringify(n.expectation) : "geen bron voor marktverwachtingen"}</div>
            </div>))}
        </Panel>
        <Panel title="Event-study">
          {d.event_study.length === 0 ? <Empty>Nog geen gemeten koersreacties.</Empty> : (
            <table className="w-full text-xs"><thead className="text-left text-slate-500"><tr><th>Categorie</th><th>Instrument</th><th>n</th><th>gem. σ</th></tr></thead>
              <tbody>{d.event_study.map((r: Any, i: number) => <tr key={i} className="border-t border-white/5" title={r.conclusion}><td>{r.category}</td><td className="font-mono">{r.symbol}</td><td>{r.events}</td><td className="num">{num(r.mean_z, 2)}</td></tr>)}</tbody></table>)}
          <p className="mt-2 text-[11px] text-slate-500">Reactie gemeten vanaf de laatste slotkoers vóór publicatie, in eenheden normale beweeglijkheid. Pas vanaf 8 gebeurtenissen een conclusie.</p>
        </Panel>
      </div>
    )}</Loader>
  );
}

function Memory() {
  const [kind, setKind] = useState("");
  return (
    <Loader<Any> path={`/api/evolution/memory?limit=150${kind ? `&kind=${kind}` : ""}`}>{(d) => (
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Panel title={`Besluitgeheugen (${d.total})`} action={<select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Soort" className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs">
          <option value="">alle</option><option value="executed">uitgevoerd</option><option value="rejected">afgewezen</option><option value="missed">gemist</option></select>}>
          {d.items.length === 0 ? <Empty>Nog niets vastgelegd. Een leerronde leest de besluiten van de holding en NEXUS in.</Empty> : (
            <div className="overflow-x-auto"><table className="w-full text-xs">
              <thead className="text-left text-slate-500"><tr><th className="py-1">Tijd</th><th>Soort</th><th>Instrument</th><th>Strategie</th><th>Regime</th><th>Na 20 d</th><th>Fouten</th><th>Bron</th></tr></thead>
              <tbody>{d.items.map((r: Any) => (
                <tr key={r.id} className="border-t border-white/5" title={r.explanation ?? r.reject_reason ?? ""}><td className="py-1">{time(r.ts)}</td><td>{r.kind} {r.side ?? ""}</td><td className="font-mono">{r.symbol}</td><td>{r.strategy ?? "—"}</td><td>{r.regime ?? "—"}</td>
                  <td className={`num ${tone(r.outcome?.fwd_20)}`}>{pct(r.outcome?.fwd_20, 1, true)}</td><td className="text-amber-200/80">{(r.error_tags ?? []).join(", ")}</td>
                  <td><K k={r.data_label === "SIMULATED" ? "simulated" : "actual"} /></td></tr>))}</tbody>
            </table></div>)}
        </Panel>
        <Panel title="Foutpatronen">
          {Object.keys(d.analysis.tags ?? {}).length === 0 ? <Empty>Nog geen herhaalde fouten gevonden.</Empty> : Object.entries(d.analysis.tags).map(([t, v]: [string, Any]) => (
            <div key={t} className="flex justify-between border-t border-white/5 py-1 text-xs first:border-0"><span>{t}</span><span className="num text-slate-400">{v.count}×</span></div>))}
        </Panel>
      </div>
    )}</Loader>
  );
}

function Models({ admin }: { admin: Admin }) {
  return (
    <Loader<Any[]> path="/api/evolution/models">{(ms, reload) => (
      <Panel title="Modelregister">
        {ms.length === 0 ? <Empty>Nog geen modellen. De eerste leerronde legt de huidige kampioen vast.</Empty> : (
          <div className="overflow-x-auto"><table className="w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th className="py-1">#</th><th>Model</th><th>Instrument</th><th>Status</th><th>Sharpe WF</th><th>P(&gt; bron)</th><th>P(&gt; K&amp;H)</th><th>Goedgekeurd</th><th /></tr></thead>
            <tbody>{ms.map((m) => (
              <tr key={m.id} className="border-t border-white/5" title={m.notes ?? ""}><td className="py-1">{m.id}</td><td>{m.key} v{m.version}</td><td className="font-mono">{(m.symbols ?? []).join(", ")}</td>
                <td>{m.role === "champion" ? <b className="text-cyan-200">kampioen</b> : m.status}</td><td className="num">{sh(m.metrics?.sharpe)}</td>
                <td className="num">{p0(m.metrics?.p_vs_baseline)}</td><td className="num">{p0(m.metrics?.p_vs_buy_hold)}</td><td className="text-slate-500">{m.approved_by ? `${m.approved_by}, ${time(m.approved_at)}` : "—"}</td>
                <td className="flex gap-1 py-1">
                  {m.role !== "champion" && <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post(`/api/evolution/models/${m.id}/promote`, { target: "paper", reason: "via Evolution Lab" }, reload)}>Naar paper</Btn>}
                  {m.role === "champion" && m.parent_id && <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post(`/api/evolution/models/${m.id}/rollback`, undefined, reload)}>Terugdraaien</Btn>}
                </td></tr>))}</tbody>
          </table></div>)}
        <p className="mt-2 text-[11px] text-slate-500">Promoveren controleert de arena-poorten opnieuw; zonder geslaagde holdout weigert de server. Kampioen worden vraagt ook 30 paperdagen. Niets hiervan zet live handelen aan.</p>
      </Panel>
    )}</Loader>
  );
}

function External({ admin }: { admin: Admin }) {
  const [content, setContent] = useState("");
  const [fmt, setFmt] = useState<"csv" | "json">("csv");
  const [cap, setCap] = useState("");
  const [cmp, setCmp] = useState<Any>(null);
  return (
    <Loader<Any[]> path="/api/external">{(batches, reload) => (
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Resultaten van een ander systeem importeren">
          <p className="mb-2 text-xs text-slate-400">CSV of JSON met per trade: timestamp, asset, direction, entry, exit, size, fees, slippage, realized_pnl, equity, strategy. Alleen totalen? Dan blijft de vergelijking onvolledig.</p>
          <div className="mb-2 flex gap-2">
            <select value={fmt} onChange={(e) => setFmt(e.target.value as "csv" | "json")} aria-label="Formaat" className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs"><option value="csv">CSV</option><option value="json">JSON</option></select>
            <input value={cap} onChange={(e) => setCap(e.target.value)} placeholder="startkapitaal €" aria-label="Startkapitaal" className="w-32 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs" />
            <input type="file" accept=".csv,.json" aria-label="Bestand" className="text-xs" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setContent(await f.text()); setFmt(f.name.endsWith(".json") ? "json" : "csv"); } }} />
          </div>
          <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={6} aria-label="Inhoud" className="w-full rounded-md border border-slate-700 bg-slate-900 p-2 font-mono text-[11px]" />
          <Btn disabled={!admin.token || !content || !!admin.busy} onClick={() => admin.post("/api/external/import", { system: "grok", format: fmt, content, starting_capital_eur: cap ? Number(cap) : null }, reload)}>Importeren</Btn>
          <h3 className="eyebrow mt-4 mb-1">Imports</h3>
          {batches.length === 0 ? <Empty>Nog niets geïmporteerd.</Empty> : batches.map((b) => (
            <div key={b.id} className="flex items-center justify-between border-t border-white/5 py-1 text-xs"><span>#{b.id} {b.system} · {b.completeness} · {b.trades} trades</span>
              <Btn onClick={async () => setCmp(await api<Any>(`/api/external/${b.id}/compare`))}>Vergelijken</Btn></div>))}
        </Panel>
        <Panel title="Vergelijking">
          {!cmp ? <Empty>Kies een import om te vergelijken met de NEXUS paper-account.</Empty> : (
            <>
              <p className={`text-sm ${cmp.status === "compared" ? "text-slate-100" : "text-amber-200/90"}`}>{cmp.verdict}</p>
              {cmp.external && cmp.nexus && (
                <table className="mt-3 w-full text-xs"><thead className="text-left text-slate-500"><tr><th /><th>Extern <K k="actual" /></th><th>NEXUS <K k="actual" /></th></tr></thead>
                  <tbody>{([["Trades", "trades", (v: number) => num(v, 0)], ["Netto resultaat", "net_pnl", (v: number) => num(v, 2)], ["Win rate", "win_rate", p0], ["Profit factor", "profit_factor", sh], ["Verwachting per trade", "expectancy", (v: number) => num(v, 2)], ["Max daling", "max_drawdown", p0], ["Sharpe (dag)", "sharpe_daily", sh], ["Handelsdagen", "days", (v: number) => num(v, 0)]] as [string, string, (v: number) => string][]).map(([l, k, f]) => (
                    <tr key={k} className="border-t border-white/5"><td className="py-1 text-slate-400">{l}</td><td className="num">{cmp.external[k] == null ? "—" : f(cmp.external[k])}</td><td className="num">{cmp.nexus[k] == null ? "—" : f(cmp.nexus[k])}</td></tr>))}</tbody></table>)}
              {cmp.comparability && <p className="mt-2 text-[11px] text-slate-500">Zelfde kapitaal: {cmp.comparability.same_capital ? "ja" : "nee"} · gedeelde instrumenten: {cmp.comparability.instrument_overlap.join(", ") || "geen"} · kosten bekend: {cmp.comparability.fees_known ? "ja" : "nee"}</p>}
              {cmp.notes?.length > 0 && <ul className="mt-2 list-disc pl-4 text-[11px] text-slate-500">{cmp.notes.map((n: string) => <li key={n}>{n}</li>)}</ul>}
            </>)}
        </Panel>
      </div>
    )}</Loader>
  );
}
