"use client";

import { useState } from "react";
import { Btn, useAdmin } from "@/components/admin";
import { Empty, PageTitle, Panel, Segmented, Skeleton, StatusDot } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, num, pct } from "@/lib/format";

interface Prov {
  key: string; name: string; group: string; host: string; note: string; required_env: string[]; missing_env: string[];
  state: State; last_check: string | null; last_success: string | null; last_failure: string | null; last_failure_class: string | null;
  freshness: { newest: string; age_hours: number; stale: boolean } | null; mode: string;
  error_class: string | null; explain: string | null; http_status: number | null; latency_ms: number | null;
  rate_limit: Record<string, string> | null; detail: { network?: string; items?: number; error?: string };
  ai_cost_30d_usd: number | null; ai_calls_30d: number;
}
interface AiProv { provider: string; usable: boolean; reason: string; model: string | null; price_per_mtok_usd: { input: number; output: number } | null; max_calls_per_day: number }
type State = "CONNECTED" | "DEGRADED" | "DISCONNECTED" | "SIMULATED" | "NOT CONFIGURED";
interface Sim { key: string; name: string; state: State; mode: string; note: string }
interface Providers { providers: Prov[]; ai: AiProv[]; simulated: Sim[] }
interface Gw {
  policies: Record<string, { providers: string[]; purpose: string; effort: string }>; deterministic_only: string[];
  routes: Record<string, { provider: string; status: string }[]>;
  usage_30d: { provider: string; task: string; calls: number; ok: number; errors: number; median_latency_ms: number | null; cost_usd: number }[];
  spent_today_usd: number; budget_left_usd: number;
}
interface Health {
  alerts: { level: string; kind: string; text: string; detail?: string }[];
  jobs: { job: string; cadence: string; description: string; uses_ai: boolean; last_status: string | null; last_started: string | null }[];
  queue: Record<string, number>; data_freshness: { newest_daily_bar: string; age_days: number } | null;
  ai_budget: { daily_budget_usd: number; spent_today_usd: number; council_spent_today_usd: number; left_usd: number };
  breakers_open: string[]; audit_chain_ok: boolean; retry_policy: Record<string, string>;
}
interface Entrant { entrant: string; kind: string; status: string; reason?: string; n?: number; accuracy?: number; macro_f1?: number; cost_usd?: number; cost_known?: boolean; median_latency_ms?: number | null; invalid?: number; verdict?: string; vs_deterministic_ci95?: [number, number] }
interface Eval { latest: { benchmark: string; frozen: string; note: string; items: number; entrants: Entrant[]; measured_at: string } | null; calibration: { rows: { provider: string; n: number; brier: number; verdict: string }[]; note: string } }

const GROUPS: [string, string][] = [["ai", "AI-aanbieders"], ["social", "Sociaal"], ["onchain", "On-chain"], ["news", "Nieuws"], ["market", "Marktdata"]];
const STATE: Record<State, [string, string, string]> = {
  CONNECTED: ["CONNECTED", "text-emerald-300", "ok"], DEGRADED: ["DEGRADED", "text-amber-300", "degraded"],
  DISCONNECTED: ["DISCONNECTED", "text-rose-300", "down"], SIMULATED: ["SIMULATED", "text-violet-300", "configured"],
  "NOT CONFIGURED": ["NOT CONFIGURED", "text-slate-400", "not_configured"],
};
const NET: Record<string, string> = {
  reachable: "host bereikbaar", network_blocked: "host geblokkeerd door deze omgeving", timeout: "time-out", network_unreachable: "geen verbinding",
};

export default function Page() {
  const admin = useAdmin();
  const prov = useApi<Providers>("/api/providers", 60_000);
  const gw = useApi<Gw>("/api/ai/gateway", 60_000);
  const health = useApi<Health>("/api/ops/health", 60_000);
  const ev = useApi<Eval>("/api/ai/eval", 300_000);
  const [group, setGroup] = useState("ai");

  return (
    <>
      <PageTitle title="Provider Control Center"
        sub="Welke bronnen en AI-aanbieders echt werken, en als iets niet werkt: waarom. Sleutels staan alleen op de server en worden hier nooit getoond; je ziet alleen welke variabele ontbreekt."
        right={<div className="flex items-center gap-3">{admin.field}
          <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/providers/check", {}, () => { prov.refresh(); health.refresh(); })}>Alles nu testen</Btn></div>} />

      <div className="space-y-5">
        {health.data && <Alerts h={health.data} />}

        <Panel title="Bronnen" action={<Segmented label="Groep" value={group} onChange={setGroup} options={GROUPS} />}>
          {prov.loading && !prov.data ? <Skeleton className="h-64" /> : !prov.data ? <Empty>Niet te laden.</Empty> : (
            <div className="-mx-1 overflow-x-auto">
              <table className="w-full min-w-[860px] text-[13px]">
                <thead><tr className="caption text-left">
                  <th className="px-1 pb-2.5 font-normal">Bron</th><th className="pb-2.5 font-normal">Status</th><th className="pb-2.5 font-normal">Waarom</th>
                  <th className="pb-2.5 font-normal">Laatst gelukt</th><th className="pb-2.5 text-right font-normal">Latency</th>
                  <th className="pb-2.5 pl-4 font-normal">Limiet</th><th className="pb-2.5 text-right font-normal">AI-kosten 30d</th></tr></thead>
                <tbody>
                  {prov.data.providers.filter((p) => p.group === group).map((p) => {
                    const [t, c, dot] = STATE[p.state];
                    return (
                      <tr key={p.key} className="border-t border-white/[.04] align-top">
                        <td className="px-1 py-2.5"><div className="text-slate-100">{p.name}</div><div className="text-[11.5px] text-slate-500">{p.host}</div></td>
                        <td className={`py-2.5 ${c}`}><span className="inline-flex items-center gap-2 font-mono text-[11.5px]"><StatusDot status={dot} />{t}</span><div className="text-[11px] text-slate-500">{p.mode}</div></td>
                        <td className="py-2.5 pr-4 text-slate-400">
                          {p.explain ?? (p.state === "CONNECTED" ? "test geslaagd" : "—")}
                          {p.freshness && <div className={`text-[11.5px] ${p.freshness.stale ? "text-amber-300" : "text-slate-500"}`}>nieuwste bericht {num(p.freshness.age_hours, 1)} u oud{p.freshness.stale ? " · VEROUDERD" : ""}</div>}
                          {p.missing_env.length > 0 && <div className="font-mono text-[11px] text-amber-300/90">{p.missing_env.join(", ")}</div>}
                          {p.detail?.network && <div className="text-[11.5px] text-slate-500">{NET[p.detail.network] ?? p.detail.network}</div>}
                        </td>
                        <td className="py-2.5 text-slate-400">{p.last_success ? ago(p.last_success) : "nooit"}<div className="text-[11.5px] text-slate-600">{p.last_check ? `getest ${ago(p.last_check)}` : "nog niet getest"}</div>
                          {p.last_failure && <div className="text-[11.5px] text-rose-300/70">fout {ago(p.last_failure)} · {p.last_failure_class}</div>}</td>
                        <td className="num py-2.5 text-right text-slate-400">{p.latency_ms != null ? `${p.latency_ms} ms` : "—"}</td>
                        <td className="py-2.5 pl-4 font-mono text-[11px] text-slate-500">{p.rate_limit && Object.keys(p.rate_limit).length ? Object.entries(p.rate_limit).map(([k, v]) => `${k.replace(/^x-|ratelimit-|rate-limit-/g, "")}: ${v}`).join(" · ") : "—"}</td>
                        <td className="num py-2.5 text-right text-slate-300">{p.group === "ai" ? (p.ai_calls_30d ? `$${num(p.ai_cost_30d_usd, 2)} · ${p.ai_calls_30d}×` : "$0,00") : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="mt-4 flex flex-wrap gap-x-8 gap-y-2 border-t border-white/[.05] pt-3 text-[12.5px]">
                {prov.data.simulated.map((x) => (
                  <div key={x.key} className="flex items-center gap-2"><StatusDot status={STATE[x.state][2]} />
                    <span className="text-slate-200">{x.name}</span><span className={`font-mono text-[11px] ${STATE[x.state][1]}`}>{x.state}</span>
                    <span className="text-slate-500">· {x.mode}</span></div>
                ))}
              </div>
              <p className="mt-2 text-[11.5px] text-slate-500">Groen (CONNECTED) betekent: een echte test tegen de aanbieder is gelukt. Geslaagde unit-tests tellen daar niet voor.</p>
            </div>
          )}
        </Panel>

        <Activation admin={admin} />

        <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
          <Panel title="AI Gateway · routering per taak" action={gw.data && <span className="caption num">vandaag ${num(gw.data.spent_today_usd, 2)} · over ${num(gw.data.budget_left_usd, 2)}</span>}>
            {!gw.data ? <Skeleton className="h-64" /> : (
              <>
                <ul className="divide-y divide-white/[.05]">
                  {Object.entries(gw.data.policies).map(([task, p]) => (
                    <li key={task} className="grid gap-2 py-2.5 text-[13px] md:grid-cols-[220px_1fr]">
                      <div><div className="text-slate-100">{task}</div><div className="text-[11.5px] text-slate-500">{p.purpose}</div></div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {gw.data!.routes[task].map((r, i) => (
                          <span key={r.provider} className="inline-flex items-center gap-1.5">
                            <span title={r.status} className={`rounded-md border px-2 py-0.5 text-[12px] ${r.status === "ok" ? "border-cyan-300/40 text-cyan-200" : "border-white/[.07] text-slate-500"}`}>{r.provider}</span>
                            {i < gw.data!.routes[task].length - 1 && <span className="text-slate-700">→</span>}
                          </span>
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-[12px] leading-relaxed text-slate-500">Nooit naar een taalmodel: {gw.data.deterministic_only.join(", ")}. Dat rekent NEXUS met vaste code. Een blauwe provider is nu bruikbaar; grijs betekent dat de sleutel of modelnaam ontbreekt, of dat het budget of de stroomonderbreker hem tegenhoudt.</p>
              </>
            )}
          </Panel>
          <Panel title="AI-aanbieders">
            {!prov.data ? <Skeleton className="h-48" /> : (
              <ul className="space-y-3 text-[13px]">
                {prov.data.ai.map((a) => (
                  <li key={a.provider} className="flex gap-2.5">
                    <span className="mt-1.5"><StatusDot status={a.usable ? "ok" : "not_configured"} /></span>
                    <div><div className="text-slate-100">{a.provider} <span className="text-slate-500">{a.model ?? ""}</span></div>
                      <div className="text-[11.5px] text-slate-500">{a.usable ? `max ${a.max_calls_per_day} aanroepen per dag · ${a.price_per_mtok_usd ? `$${a.price_per_mtok_usd.input}/$${a.price_per_mtok_usd.output} per mln tokens` : "prijs onbekend: zet NEXUS_*_PRICE_IN/OUT"}` : a.reason}</div></div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <Panel title="AI Evaluation Arena · nieuwsclassificatie"
          action={<Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/ai/eval", undefined, ev.refresh)}>Opnieuw meten</Btn>}>
          {!ev.data ? <Skeleton className="h-40" /> : !ev.data.latest ? <Empty>Nog niet gemeten. &ldquo;Opnieuw meten&rdquo; scoort de vaste regels en elke ingestelde AI-aanbieder op dezelfde 30 koppen.</Empty> : (
            <>
              <div className="-mx-1 overflow-x-auto">
                <table className="w-full min-w-[720px] text-[13px]">
                  <thead><tr className="caption text-left"><th className="px-1 pb-2.5 font-normal">Deelnemer</th><th className="pb-2.5 text-right font-normal">Nauwkeurigheid</th>
                    <th className="pb-2.5 text-right font-normal">Macro-F1</th><th className="pb-2.5 text-right font-normal">Kosten</th><th className="pb-2.5 text-right font-normal">Latency</th><th className="pb-2.5 pl-4 font-normal">Oordeel</th></tr></thead>
                  <tbody>
                    {ev.data.latest.entrants.map((e) => (
                      <tr key={e.entrant} className="border-t border-white/[.04]">
                        <td className="px-1 py-2.5 text-slate-100">{e.entrant} <span className="text-slate-500">· {e.kind}</span></td>
                        {e.status === "measured" ? <>
                          <td className="num py-2.5 text-right text-white">{pct(e.accuracy, 0)}</td>
                          <td className="num py-2.5 text-right text-slate-300">{num(e.macro_f1, 2)}</td>
                          <td className="num py-2.5 text-right text-slate-300">{e.cost_known === false ? "onbekend" : `$${num(e.cost_usd, 3)}`}</td>
                          <td className="num py-2.5 text-right text-slate-400">{e.median_latency_ms != null ? `${e.median_latency_ms} ms` : "—"}</td>
                          <td className="py-2.5 pl-4 text-slate-400">{e.verdict ?? "basislijn"}</td>
                        </> : <td colSpan={5} className="py-2.5 text-slate-500">niet gemeten: {e.reason}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-[12px] leading-relaxed text-slate-500">{ev.data.latest.note} Set bevroren op {ev.data.latest.frozen}; gemeten {ago(ev.data.latest.measured_at)}.</p>
              <p className="mt-1 text-[12px] text-slate-500">Kalibratie van voorspellingen: {ev.data.calibration.note}</p>
            </>
          )}
        </Panel>

        <Labelling admin={admin} />

        <Debates admin={admin} />

        {health.data && (
          <Panel title="Achtergrondtaken" action={<span className="caption">{health.data.retry_policy.ai}</span>}>
            <div className="grid gap-x-6 gap-y-2 text-[13px] md:grid-cols-2 xl:grid-cols-3">
              {health.data.jobs.map((j) => (
                <div key={j.job} className="flex gap-2.5">
                  <span className="mt-1.5"><StatusDot status={j.last_status === "ok" ? "ok" : j.last_status === "failed" ? "down" : j.last_status ? "degraded" : "disabled"} /></span>
                  <div className="min-w-0"><div className="text-slate-200">{j.job} <span className="text-slate-500">· {j.cadence}{j.uses_ai ? " · AI" : ""}</span></div>
                    <div className="truncate text-[11.5px] text-slate-500" title={j.description}>{j.last_started ? `${j.last_status} · ${ago(j.last_started)}` : "nog niet gedraaid"}</div></div>
                </div>
              ))}
            </div>
          </Panel>
        )}
      </div>
    </>
  );
}

function Alerts({ h }: { h: Health }) {
  const c = { high: "bg-rose-500", medium: "bg-amber-400", info: "bg-cyan-300" } as Record<string, string>;
  return (
    <section className="panel fade-up grid gap-6 p-5 md:grid-cols-[1fr_auto]" aria-label="Bewaking">
      <div>
        <div className="caption mb-2">Meldingen</div>
        {h.alerts.length ? (
          <ul className="space-y-1.5 text-[13px]">
            {h.alerts.map((a, i) => <li key={i} className="flex gap-2.5"><span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${c[a.level] ?? "bg-slate-500"}`} /><span className="text-slate-200">{a.text}{a.detail && <span className="text-slate-500"> · {a.detail}</span>}</span></li>)}
          </ul>
        ) : <div className="text-[13px] text-slate-400">Geen meldingen.</div>}
      </div>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-[13px] md:grid-cols-4">
        <div><dt className="caption">AI-budget vandaag</dt><dd className="num mt-1 text-white">${num(h.ai_budget.spent_today_usd + h.ai_budget.council_spent_today_usd, 2)} / ${num(h.ai_budget.daily_budget_usd, 2)}</dd></div>
        <div><dt className="caption">Wachtrij</dt><dd className="num mt-1 text-white">{(h.queue.queued ?? 0) + (h.queue.running ?? 0)} open · {h.queue.escalated ?? 0} CEO</dd></div>
        <div><dt className="caption">Nieuwste dagkoers</dt><dd className="num mt-1 text-white">{h.data_freshness ? `${num(h.data_freshness.age_days, 1)} d oud` : "—"}</dd></div>
        <div><dt className="caption">Auditketen</dt><dd className={`mt-1 ${h.audit_chain_ok ? "text-emerald-300" : "text-rose-300"}`}>{h.audit_chain_ok ? "intact" : "gebroken"}</dd></div>
      </dl>
    </section>
  );
}

interface DebateRow { id: number; subject: string; status: string; author: string | null; challenger: string | null; independent: boolean; created_at: string; cost_usd: number;
  summary: { recommendation: string; independence: string; agreements: unknown[]; disagreements: unknown[]; unsupported: unknown[] } }
interface Hyp { id: number; title: string; status: string }

function Debates({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const { data, refresh } = useApi<DebateRow[]>("/api/ai/debates", 60_000);
  const hyps = useApi<Hyp[]>("/api/evolution/hypotheses", 300_000);
  const [hid, setHid] = useState<string>("");
  return (
    <Panel title="Onafhankelijk debat" action={<div className="flex items-center gap-2">
      <select aria-label="Hypothese" value={hid} onChange={(e) => setHid(e.target.value)}
        className="max-w-64 rounded-md border border-white/[.08] bg-[#0F1217] px-2 py-1.5 text-[12.5px] text-slate-200">
        <option value="">Kies een hypothese…</option>
        {(hyps.data ?? []).map((h) => <option key={h.id} value={h.id}>#{h.id} {h.title} ({h.status})</option>)}
      </select>
      <Btn disabled={!admin.token || !hid || !!admin.busy} onClick={() => admin.post("/api/ai/debate", { hypothesis_id: Number(hid) }, refresh)}>Debat starten</Btn>
    </div>}>
      <p className="mb-4 text-[12.5px] leading-relaxed text-slate-400">Onderzoeker → onafhankelijke uitdager (bij voorkeur een andere aanbieder) → Quant Engine (vaste code) → Risk Guardian (vaste regels) → samenvatting → CEO. Beweringen zonder verwijzing naar echte data tellen als &ldquo;zonder bewijs&rdquo;, ook als het tweede model ze herhaalt.</p>
      {!data?.length ? <Empty>Nog geen debatten.</Empty> : (
        <ul className="divide-y divide-white/[.05] text-[13px]">
          {data.map((d) => (
            <li key={d.id} className="grid gap-1 py-3 md:grid-cols-[1fr_auto]">
              <div><div className="text-slate-100">#{d.id} {d.subject}</div>
                <div className="text-[11.5px] text-slate-500">{d.author ?? "—"} vs {d.challenger ?? "—"} · {d.summary.independence} · {d.summary.agreements.length} gedeeld, {d.summary.disagreements.length} betwist, {d.summary.unsupported.length} zonder bewijs</div></div>
              <div className="text-right"><div className={d.status === "done" ? "text-slate-200" : "text-slate-500"}>{d.summary.recommendation}</div><div className="text-[11.5px] text-slate-500">{ago(d.created_at)} · ${num(d.cost_usd, 3)}</div></div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

interface Act { status: string; at: string; reason?: string; run_id?: number;
  connectivity: { status: string; error_class: string | null; latency_ms: number | null };
  live_call?: { provider: string; model: string; latency_ms: number; tokens_in: number; tokens_out: number; estimated_cost_usd: number | null; actual_cost_usd: number | null };
  checks: { check: string; ok: boolean; detail: string }[] }

function Activation({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const { data, refresh } = useApi<{ latest: Act | null }>("/api/activation/council", 120_000);
  const a = data?.latest;
  const tone = a?.status === "CONNECTED" ? "text-emerald-300" : a?.status === "DEGRADED" ? "text-amber-300" : "text-slate-300";
  return (
    <Panel title="Council-activatie · eerste echte AI-taak"
      action={<Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/activation/council", undefined, refresh)}>Activatietest draaien</Btn>}>
      {!a ? <Empty>Nog niet gedraaid. De test doet één kleine onderzoeksvraag met echte feiten, plus een fallback-, budget- en CEO-escalatietest. Zonder sleutel wordt niets verstuurd.</Empty> : (
        <div className="grid gap-5 md:grid-cols-[260px_1fr] text-[13px]">
          <div>
            <div className={`font-mono text-[15px] ${tone}`}>{a.status.replace("_", " ")}</div>
            <div className="mt-1 text-[11.5px] text-slate-500">{ago(a.at)} · verbinding: {a.connectivity.status}{a.connectivity.error_class ? ` (${a.connectivity.error_class})` : ""}</div>
            {a.reason && <p className="mt-2 text-slate-400">{a.reason}</p>}
          </div>
          {a.live_call ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-4">
              <div><dt className="caption">Model (echt)</dt><dd className="mt-0.5 font-mono text-[12px] text-white">{a.live_call.model}</dd></div>
              <div><dt className="caption">Latency</dt><dd className="num mt-0.5 text-white">{a.live_call.latency_ms} ms</dd></div>
              <div><dt className="caption">Tokens in/uit</dt><dd className="num mt-0.5 text-white">{a.live_call.tokens_in} / {a.live_call.tokens_out}</dd></div>
              <div><dt className="caption">Kosten schatting → echt</dt><dd className="num mt-0.5 text-white">${num(a.live_call.estimated_cost_usd, 4)} → ${num(a.live_call.actual_cost_usd, 4)}</dd></div>
              {a.checks.map((c) => <div key={c.check} className="col-span-2 flex gap-2"><StatusDot status={c.ok ? "ok" : "down"} /><span className="text-slate-300">{c.check}</span><span className="truncate text-slate-500">{c.detail}</span></div>)}
            </dl>
          ) : <p className="text-slate-500">Geen echte aanroep gedaan, dus geen model, latency of kosten om te tonen.</p>}
        </div>
      )}
    </Panel>
  );
}

interface LabelItem { id: number; title: string; source: string; published_at: string }
interface LabelStatus { labels: { labelled: number; test_items: number; dev_items: number; min_for_verdict: number; note: string } }

function Labelling({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const st = useApi<LabelStatus>("/api/eval/status", 120_000);
  const [queue, setQueue] = useState<{ items: LabelItem[]; labels: string[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function load() {
    setErr(null);
    try { setQueue(await api("/api/eval/label-queue?limit=10", { headers: { Authorization: `Bearer ${admin.token}` } })); }
    catch (e) { setErr(e instanceof Error ? e.message : "laden mislukt"); }
  }
  function label(id: number, l: string) {
    admin.post("/api/eval/labels", { news_id: id, label: l }, () => { setQueue((q) => q && { ...q, items: q.items.filter((x) => x.id !== id) }); st.refresh(); });
  }
  const s = st.data?.labels;
  return (
    <Panel title="Onafhankelijke eval-set · koppen labelen"
      action={<div className="flex items-center gap-3">{s && <span className="caption num">{s.labelled} gelabeld · test {s.test_items}/{s.min_for_verdict}</span>}
        <Btn disabled={!admin.token} onClick={load}>Koppen laden</Btn></div>}>
      <p className="mb-3 text-[12.5px] leading-relaxed text-slate-400">{s?.note ?? "Echte koppen, gelabeld door een mens die de regels niet schreef."} Je ziet alleen kop en bron, niet wat NEXUS ervan denkt.</p>
      {err && <p className="text-[12.5px] text-rose-300">{err}</p>}
      {!queue ? <Empty>Laad koppen met het admin- of operator-token.</Empty> : !queue.items.length ? <Empty>Geen ongelabelde echte berichten. Echte feeds moeten eerst binnenkomen (fixtures tellen niet).</Empty> : (
        <ul className="divide-y divide-white/[.05] text-[13px]">
          {queue.items.map((it) => (
            <li key={it.id} className="grid gap-2 py-2.5 md:grid-cols-[1fr_240px]">
              <div><div className="text-slate-100">{it.title}</div><div className="text-[11.5px] text-slate-500">{it.source} · {ago(it.published_at)}</div></div>
              <select aria-label={`Label voor ${it.id}`} defaultValue="" onChange={(e) => e.target.value && label(it.id, e.target.value)}
                className="rounded-md border border-white/[.08] bg-[#0F1217] px-2 py-1.5 text-[12.5px] text-slate-200">
                <option value="">Kies label…</option>
                {queue.labels.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
