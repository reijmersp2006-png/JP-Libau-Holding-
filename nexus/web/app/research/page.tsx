"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Btn, useAdmin } from "@/components/admin";
import { KpiCell, KpiStrip, PageHeader, Provenance, Tabs } from "@/components/ds";
import { Empty, ErrorBox, Panel, Skeleton, StatusDot } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, num, pct } from "@/lib/format";

/* CEO Control Center voor Genesis: onderzoek aanvragen en volgen, bewijs en meningsverschillen lezen,
   AI-onderzoek pauzeren, kosten, mislukte taken en gereedheid. Raakt nooit orders, limieten of de noodstop. */

interface RStep {
  step: string; agent: string; status: string; at: string; ms: number | null; model: string | null; provider: string | null;
  evidence: string[]; decision: string | null; cost_usd: number | null; detail: Record<string, unknown>;
}
interface Msg { from: string; to: string; purpose: string; question?: string | null; findings: unknown[]; evidence: string[]; assumptions: string[]; uncertainties: string[]; contradictions: string[]; next: string[] }
interface Disagreement { topic: string; kind: string; severity: string; between: string[]; author_position: string | null; challenger_evidence: string[] }
interface Conclusion {
  main_hypothesis?: string; supporting_evidence?: { text: string; evidence: string[]; confidence: number }[];
  counterarguments?: string[]; quantitative_findings?: Record<string, unknown>; missing_information?: string[];
  risk_considerations?: string[]; recommendation?: string; escalation?: string; disagreements?: Disagreement[];
  confidence?: { assessed: string; author_prob_up: number | null; baseline_prob_up: number | null; challenger_confidence: number | null; rule: string };
  challenge?: { rule_findings: number; high: number; ai_objections: number; independent_provider: boolean | null; revision: unknown };
  data?: { label: string; asof: string | null; simulated_inputs: boolean }; fallback_deterministic?: boolean; not_advice?: string;
}
interface Row {
  id: number; trace_id: string; subject: string; question: string; mode: string; variant: string; requested_by: string; status: string;
  simulated: boolean; cost_usd: number | null; max_cost_usd: number | null; eval_run: string | null; created_at: string; finished_at: string | null;
  recommendation: string | null; assessed_confidence: string | null; disagreements: number; ai_steps: number; blocked_steps: string[];
}
interface Full extends Row { steps: RStep[]; messages: Msg[]; conclusion: Conclusion }
interface Readiness {
  ai: { provider: string; usable: boolean; reason: string; model: string | null; price_per_mtok_usd: { input: number; output: number } | null }[];
  providers: { key: string; name: string; group: string; state: string; missing_env: string[]; last_check: string | null; last_failure_class: string | null }[];
  budget: { daily_usd: number; left_usd: number; max_run_usd: number }; pause: { paused: boolean; by?: string; reason?: string; at?: string } | null;
  research_per_day: number; roles: { key: string; name: string; kind: string; status: string; code_status: string | null; ai_status: string | null }[]; live_trading: boolean;
}
interface Estimate { max_cost_usd: number; unknown_price_steps: string[]; budget_left_usd: number; providers: Record<string, string | null> }

const MODES: [string, string][] = [["deterministic", "A · alleen vaste code"], ["single", "B · één analist"], ["challenger", "C · analist + uitdager"], ["council", "D · volledige Council"]];
const SYMBOLS = ["BTC-EUR", "ETH-EUR", "SOL-EUR", "DOGE-EUR", "IWDA.AS", "ASML.AS", "NVDA", "AAPL", "GC=F", "EURUSD=X"];
const STATUS_DOT: Record<string, string> = { ok: "ok", done: "ok", partial: "degraded", warning: "degraded", blocked: "not_configured", skipped: "disabled", not_applicable: "disabled", failed: "down", running: "degraded" };
const REC: Record<string, string> = { no_further_research: "geen vervolg", monitor: "volgen", further_research: "verder onderzoek", escalate_to_ceo: "naar de CEO" };
type Tab = "werk" | "ledger" | "evaluatie" | "kosten" | "gereedheid";

export default function Page() {
  const [tab, setTab] = useState<Tab>("werk");
  useEffect(() => {
    const h = window.location.hash.replace("#", "") as Tab;
    if (["werk", "ledger", "evaluatie", "kosten", "gereedheid"].includes(h)) { const t = setTimeout(() => setTab(h), 0); return () => clearTimeout(t); }
  }, []);
  const ready = useApi<Readiness>("/api/genesis/readiness", 60_000);
  const admin = useAdmin();
  const paused = !!ready.data?.pause?.paused;

  return (
    <div className="page-in">
      <PageHeader eyebrow="Genesis · CEO Control Center" title="AI-onderzoek"
        sub="Vraag onderzoek aan, volg elke stap met bewijs, kosten en meningsverschillen, en houd de Prediction Ledger bij. Onderzoeksrechten staan los van handelsrechten: niets hier plaatst orders of wijzigt limieten."
        right={<div className="flex flex-wrap items-center gap-2">{admin.field}
          {paused
            ? <Btn primary disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/research/resume", undefined, () => ready.refresh())}>Pauze opheffen (CEO)</Btn>
            : <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/research/pause", { reason: "gepauzeerd via CEO Control Center" }, () => ready.refresh())}>AI-onderzoek pauzeren</Btn>}
        </div>} />
      {paused && <div role="status" className="mb-4 rounded-lg border border-amber-300/25 bg-amber-300/[.05] px-4 py-2.5 text-[13px] text-amber-100">
        AI-onderzoek is gepauzeerd{ready.data?.pause?.by ? ` door ${ready.data.pause.by}` : ""}{ready.data?.pause?.at ? ` (${ago(ready.data.pause.at)})` : ""}. Vaste code blijft draaien en het auditspoor loopt door. Alleen het admin-token heft de pauze op.</div>}
      <p className="t-micro mb-4">Token: het onderzoeks-, operator- of admin-token mag onderzoek aanvragen en pauzeren; pauze opheffen, ledger-correcties en de vergelijking A–D (betaald) alleen admin. Het token blijft in dit tabblad.</p>
      <div className="mb-5"><Tabs label="Onderdelen" value={tab} onChange={(t) => { setTab(t); history.replaceState(null, "", `#${t}`); }}
        items={[["werk", "Opdrachten"], ["ledger", "Prediction Ledger"], ["evaluatie", "Evaluatie"], ["kosten", "Kosten en storingen"], ["gereedheid", "Gereedheid"]]} /></div>
      {tab === "werk" && <Work admin={admin} ready={ready.data} />}
      {tab === "ledger" && <Ledger admin={admin} />}
      {tab === "evaluatie" && <Evaluation admin={admin} />}
      {tab === "kosten" && <Costs />}
      {tab === "gereedheid" && <ReadinessView r={ready.data} loading={ready.loading} error={ready.error} />}
    </div>
  );
}

// ── Opdrachten ───────────────────────────────────────────────────────────────────────────
function Work({ admin, ready }: { admin: ReturnType<typeof useAdmin>; ready: Readiness | null }) {
  const list = useApi<{ items: Row[]; per_day: number }>("/api/research?limit=40&include_eval=true", 30_000);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("trace");
    if (t) { const h = setTimeout(() => setSel(t), 0); return () => clearTimeout(h); }
  }, []);
  const current = sel ?? list.data?.items[0]?.trace_id ?? null;
  const one = useApi<Full>(current ? `/api/research/${encodeURIComponent(current)}` : null, 60_000);

  return (
    <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
      <div className="space-y-5 xl:self-start">
        <RequestForm admin={admin} ready={ready} onDone={(t) => { list.refresh(); setSel(t); }} />
        <Panel title={`Opdrachten · ${list.data?.items.length ?? 0}`} className="!p-3">
          {list.loading && !list.data ? <Skeleton className="h-40" /> : list.error ? <ErrorBox message={list.error} onRetry={list.refresh} /> : !list.data?.items.length ? (
            <Empty>Nog geen onderzoeksopdrachten. Vraag er hierboven een aan.</Empty>
          ) : (
            <ul className="space-y-1">
              {list.data.items.map((x) => (
                <li key={x.trace_id}><button onClick={() => setSel(x.trace_id)} aria-current={current === x.trace_id}
                  className={`w-full rounded-md px-2.5 py-2 text-left text-[12.5px] ${current === x.trace_id ? "bg-white/[.06]" : "hover:bg-white/[.03]"}`}>
                  <div className="flex items-center gap-2"><StatusDot status={STATUS_DOT[x.status] ?? "down"} /><span className="text-slate-100">{x.subject}</span>
                    <span className="chip">{x.variant}</span>{x.eval_run && <span className="chip">eval</span>}<span className="t-micro ml-auto">{ago(x.created_at)}</span></div>
                  <div className="t-micro mt-0.5">{x.status} · {x.recommendation ? REC[x.recommendation] ?? x.recommendation : "—"} · {x.ai_steps} AI-stappen · ${num(x.cost_usd ?? 0, 4)}{x.disagreements ? ` · ${x.disagreements} meningsverschil` : ""}{x.blocked_steps.length ? ` · geblokkeerd: ${x.blocked_steps.join(", ")}` : ""}</div>
                </button></li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="min-w-0">{!current ? null : one.loading && !one.data ? <Skeleton className="h-[600px]" /> : one.error ? <ErrorBox message={one.error} onRetry={one.refresh} /> : one.data && <Trace w={one.data} />}</div>
    </div>
  );
}

function RequestForm({ admin, ready, onDone }: { admin: ReturnType<typeof useAdmin>; ready: Readiness | null; onDone: (trace: string) => void }) {
  const [subject, setSubject] = useState("BTC-EUR");
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("challenger");
  const est = useApi<Estimate>(`/api/research/estimate?mode=${mode}`, 120_000);
  const fits = est.data ? est.data.max_cost_usd <= est.data.budget_left_usd : true;
  const anyAi = (ready?.ai ?? []).some((a) => a.usable);
  return (
    <Panel title="Onderzoek aanvragen">
      <div className="space-y-3 text-[12.5px]">
        <label className="block"><span className="t-label">Onderwerp</span>
          <select value={subject} onChange={(e) => setSubject(e.target.value)} className="mt-1 w-full rounded-md border border-white/[.08] bg-[#0F1217] px-2 py-1.5 text-slate-200">
            {SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select></label>
        <label className="block"><span className="t-label">Vraag (optioneel, max. 300 tekens)</span>
          <textarea value={question} maxLength={300} rows={2} onChange={(e) => setQuestion(e.target.value)} placeholder={`Is er reden voor verder onderzoek naar ${subject}?`}
            className="mt-1 w-full rounded-md border border-white/[.08] bg-white/[.02] px-2.5 py-1.5 text-slate-200 placeholder:text-slate-600" /></label>
        <label className="block"><span className="t-label">Variant</span>
          <select value={mode} onChange={(e) => setMode(e.target.value)} className="mt-1 w-full rounded-md border border-white/[.08] bg-[#0F1217] px-2 py-1.5 text-slate-200">
            {MODES.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        <div className="rounded-md border border-white/[.06] p-2.5">
          <div className="flex justify-between"><span className="text-slate-400">Maximale kosten (vooraf)</span><span className="num text-slate-100">${num(est.data?.max_cost_usd ?? 0, 4)}</span></div>
          <div className="flex justify-between"><span className="text-slate-400">Budget over vandaag</span><span className="num text-slate-100">${num(est.data?.budget_left_usd ?? 0, 4)}</span></div>
          {mode !== "deterministic" && !anyAi && <p className="t-micro mt-1.5 text-amber-200">Geen AI-aanbieder geconfigureerd: de AI-stappen worden BLOCKED en het spoor laat zien waar het stopt. Vaste code draait wel.</p>}
          {!fits && <p className="t-micro mt-1.5 text-amber-200">Het kostenplan past niet in het resterende budget: AI-stappen worden geweigerd.</p>}
          {!!est.data?.unknown_price_steps.length && <p className="t-micro mt-1.5">Prijs onbekend voor: {est.data.unknown_price_steps.join(", ")} (die stap wordt overgeslagen).</p>}
        </div>
        <Btn primary disabled={!admin.token || !!admin.busy} onClick={() => admin.post<Full>("/api/research", { subject, question, mode }, (r) => onDone(r.trace_id))}>
          {admin.busy === "/api/research" ? "Bezig…" : "Opdracht starten"}</Btn>
        <p className="t-micro">Maximaal {ready?.research_per_day ?? 10} opdrachten per dag en ${num(ready?.budget.max_run_usd ?? 5, 2)} per opdracht (server-side).</p>
      </div>
    </Panel>
  );
}

function qfmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return num(v, Math.abs(v) < 1 ? 3 : 0);
  if (Array.isArray(v)) return v.map((x) => qfmt(x)).join(" – ");
  if (typeof v === "object") {
    const o = v as { n?: number; rate?: number | null; ci95?: number[] | null };
    if ("rate" in o) return `${o.rate != null ? pct(o.rate, 0) : "—"} (n ${o.n ?? 0}${o.ci95 ? `, ${o.ci95.map((x) => pct(x, 0)).join("–")}` : ""})`;
    return JSON.stringify(v).slice(0, 80);
  }
  return String(v);
}

function kindOf(s: RStep): "measured" | "ai" | "rule" | "human" {
  if (s.provider) return "ai";
  if (["market_context", "technical", "quant"].includes(s.step)) return "measured";
  if (s.agent === "ceo") return "human";
  return "rule";
}

function Trace({ w }: { w: Full }) {
  const c = w.conclusion ?? {};
  const [open, setOpen] = useState<number | null>(null);
  const totalMs = useMemo(() => w.steps.reduce((a, s) => a + (s.ms ?? 0), 0), [w.steps]);
  return (
    <div className="space-y-5">
      <Panel>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 basis-[26rem]">
            <div className="flex flex-wrap items-center gap-2"><code className="font-mono text-[11.5px] text-slate-500">{w.trace_id}</code><span className="chip">{w.status}</span><span className="chip">variant {w.variant}</span>
              {w.simulated && <Provenance kind="simulated" />}{c.fallback_deterministic && <span className="chip text-amber-200">terugval op vaste code</span>}</div>
            <h2 className="mt-2 text-[17px] font-medium leading-snug text-white">{w.subject}: {w.question}</h2>
            <div className="t-label mt-1.5">aangevraagd door {w.requested_by} · {new Date(w.created_at).toLocaleString("nl-NL")} · data {c.data?.label ?? "—"} t/m {c.data?.asof ? new Date(c.data.asof).toLocaleDateString("nl-NL") : "—"}</div>
          </div>
          <KpiStrip cols="grid-cols-3">
            <KpiCell label="Aanbeveling" value={c.recommendation ? REC[c.recommendation] ?? c.recommendation : "—"} />
            <KpiCell label="Vertrouwen (regel)" value={c.confidence?.assessed ?? "—"} />
            <KpiCell label="Kosten" value={`$${num(w.cost_usd ?? 0, 4)}`} sub={`plan ≤ $${num(w.max_cost_usd ?? 0, 4)} · ${Math.round(totalMs / 1000)} s`} />
          </KpiStrip>
        </div>
      </Panel>

      <Panel title="Stappen" action={<span className="t-micro">agent · model · bewijs · tijd · besluit · kosten · status</span>}>
        <ol className="divide-y divide-white/[.05]">
          {w.steps.map((s, i) => (
            <li key={`${s.step}-${i}`} className="py-2">
              <button className="grid w-full grid-cols-[18px_minmax(0,1fr)] gap-x-2 text-left text-[12.5px] md:grid-cols-[18px_150px_150px_minmax(0,1fr)_90px_80px]" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
                <StatusDot status={STATUS_DOT[s.status] ?? "down"} />
                <span className="font-mono text-slate-200">{s.step}</span>
                <span className="text-slate-400 max-md:col-start-2">{s.agent}{s.provider ? ` · ${s.provider}` : ""}</span>
                <span className="truncate text-slate-400 max-md:col-start-2">{s.decision ?? s.status}{s.model ? ` · ${s.model}` : ""}</span>
                <span className="num text-slate-500 max-md:col-start-2">{new Date(s.at).toLocaleTimeString("nl-NL")}{s.ms != null ? ` · ${s.ms} ms` : ""}</span>
                <span className="num text-right text-slate-300 max-md:col-start-2 max-md:text-left">{s.cost_usd != null ? `$${num(s.cost_usd, 4)}` : "—"}</span>
              </button>
              {open === i && (
                <div className="ml-6 mt-2 space-y-2 rounded-lg border border-white/[.05] p-3 text-[12px]">
                  <div className="flex flex-wrap items-center gap-2"><Provenance kind={kindOf(s)} /><span className="t-micro">status {s.status}</span></div>
                  {!!s.evidence.length && <p className="text-slate-400">Bewijs: <span className="font-mono text-slate-300">{s.evidence.slice(0, 30).join(", ")}{s.evidence.length > 30 ? " …" : ""}</span></p>}
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-slate-400">{JSON.stringify(s.detail, null, 2).slice(0, 6000)}</pre>
                </div>
              )}
            </li>
          ))}
        </ol>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Conclusie" action={<Provenance kind={w.ai_steps ? "ai" : "rule"} />}>
          <p className="text-[13px] leading-relaxed text-slate-100">{c.main_hypothesis ?? "Geen conclusie: de opdracht is niet afgerond."}</p>
          <h4 className="t-label mt-4">Onderbouwd (alleen geldige bron-ids, zonder ernstig bezwaar)</h4>
          {c.supporting_evidence?.length ? <ul className="mt-1.5 space-y-1.5 text-[12.5px]">{c.supporting_evidence.map((e, i) => <li key={i} className="text-slate-300">{e.text} <span className="font-mono text-[11px] text-slate-500">[{e.evidence.join(", ")}]</span></li>)}</ul> : <p className="mt-1 text-[12.5px] text-slate-500">Geen onderbouwde beweringen.</p>}
          <h4 className="t-label mt-4">Tegenargumenten</h4>
          {c.counterarguments?.length ? <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12.5px] text-slate-300">{c.counterarguments.map((t, i) => <li key={i}>{t}</li>)}</ul> : <p className="mt-1 text-[12.5px] text-slate-500">Geen.</p>}
          <h4 className="t-label mt-4">Ontbreekt</h4>
          <p className="mt-1 text-[12.5px] text-slate-300">{c.missing_information?.join(", ") || "—"}</p>
          <h4 className="t-label mt-4">Risico</h4>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12.5px] text-slate-300">{(c.risk_considerations ?? []).map((t, i) => <li key={i}>{t}</li>)}</ul>
          <p className="t-micro mt-4">{c.confidence?.rule}. Kans omhoog volgens auteur {c.confidence?.author_prob_up != null ? pct(c.confidence.author_prob_up, 0) : "—"}, historische basiskans {c.confidence?.baseline_prob_up != null ? pct(c.confidence.baseline_prob_up, 0) : "—"}. {c.not_advice}</p>
        </Panel>
        <div className="space-y-5">
          <Panel title={`Meningsverschillen · ${c.disagreements?.length ?? 0}`}>
            {c.disagreements?.length ? <ul className="space-y-3 text-[12.5px]">{c.disagreements.map((d, i) => (
              <li key={i} className="rounded-lg border border-white/[.05] p-2.5"><div className="flex flex-wrap gap-2"><span className="chip">{d.kind}</span><span className="chip">{d.severity}</span><span className="t-micro">{d.between.join(" vs ")}</span></div>
                <p className="mt-1.5 text-slate-200">{d.topic}</p>{d.author_position && <p className="t-micro mt-1">Standpunt auteur: {d.author_position}</p>}
                {!!d.challenger_evidence.length && <p className="t-micro mt-1 font-mono">{d.challenger_evidence.join(", ")}</p>}</li>))}</ul>
              : <p className="text-[12.5px] text-slate-500">Geen vastgelegde meningsverschillen.</p>}
            <p className="t-micro mt-3">Uitdager: {c.challenge?.rule_findings ?? 0} bevindingen uit vaste controles ({c.challenge?.high ?? 0} ernstig), {c.challenge?.ai_objections ?? 0} AI-bezwaren. Onafhankelijke aanbieder: {c.challenge?.independent_provider == null ? "n.v.t." : c.challenge.independent_provider ? "ja" : "nee (zelfde aanbieder telt niet als onafhankelijk)"}.</p>
          </Panel>
          <Panel title={`Overdrachten · ${w.messages.length}`}>
            <ol className="space-y-2 text-[12px]">{w.messages.map((m, i) => (
              <li key={i} className="grid grid-cols-[minmax(0,1fr)] gap-0.5 border-l border-white/[.08] pl-3"><span className="text-slate-200">{m.from} → {m.to}: {m.purpose}</span>
                <span className="t-micro">{m.evidence.length} bewijs-ids · {m.findings.length} bevindingen{m.assumptions.length ? ` · aannames: ${m.assumptions.join("; ")}` : ""}{m.uncertainties.length ? ` · onzeker: ${m.uncertainties.join("; ")}` : ""}{m.contradictions.length ? ` · tegenstrijdig: ${m.contradictions.join("; ")}` : ""}{m.next?.length ? ` · volgende: ${m.next.join("; ")}` : ""}</span></li>))}</ol>
          </Panel>
          <Panel title="Kwantitatief (vaste code, vóór de holdout)" action={<Provenance kind="measured" />}>
            <dl className="grid gap-x-4 gap-y-1.5 text-[12px] sm:grid-cols-2">{Object.entries(c.quantitative_findings ?? {}).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2"><dt className="text-slate-500">{k}</dt><dd className="num text-right text-slate-300">{qfmt(v)}</dd></div>))}</dl>
          </Panel>
        </div>
      </div>
      <p className="t-micro">Ook te zien in <Link href="/decisions" className="text-cyan-300">Decision Theater</Link>, <Link href="/hq" className="text-cyan-300">AI Headquarters</Link> en via de Copilot.</p>
    </div>
  );
}

// ── Prediction Ledger ────────────────────────────────────────────────────────────────────
interface LedgerItem { pid: string; agent: string; model: string | null; subject: string; probability: number; outcome_def: { text: string }; created_at: string; horizon_end: string; data_asof: string; evidence: string[]; workflow_trace: string | null; amendments: number; outcome: number | null; status: string }
interface Score { n: number; note?: string; brier?: number; log_loss?: number; directional_accuracy?: number; directional_ci95?: number[]; brier_skill?: number | null; calibration_note?: string }
interface LedgerData { total: number; open: number; resolved: number; due_unresolved: number; chain: { ok: boolean; checked: number; broken_at?: string }; agents: Record<string, Score>; items: LedgerItem[]; rules: string }

function Ledger({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const { data, loading, error, refresh } = useApi<LedgerData>("/api/ledger", 60_000);
  if (loading && !data) return <Skeleton className="h-96" />;
  if (error) return <ErrorBox message={error} onRetry={refresh} />;
  if (!data) return null;
  return (
    <div className="space-y-5">
      <KpiStrip cols="grid-cols-2 md:grid-cols-5">
        <KpiCell label="Voorspellingen" value={data.total} /><KpiCell label="Open" value={data.open} /><KpiCell label="Afgerekend" value={data.resolved} />
        <KpiCell label="Verlopen, nog niet afgerekend" value={data.due_unresolved} /><KpiCell label="Hash-keten" value={data.chain.ok ? "intact" : "GEBROKEN"} tone={data.chain.ok ? "" : "text-rose-300"} />
      </KpiStrip>
      <Panel title="Scores per agent" action={<Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/ledger/resolve", undefined, () => refresh())}>Verlopen afrekenen</Btn>}>
        {!Object.keys(data.agents).length ? <Empty>Nog niets afgerekend. Een voorspelling wordt pas na de vooraf vastgelegde horizon (28 dagen) door vaste code afgerekend. Geen conclusies uit kleine aantallen.</Empty> : (
          <table className="w-full text-[12.5px]"><thead><tr className="t-label text-left"><th className="py-1.5">Agent</th><th>n</th><th>Brier</th><th>Log loss</th><th>Richting (95%-CI)</th><th>Brier-skill t.o.v. basiskans</th></tr></thead>
            <tbody>{Object.entries(data.agents).map(([a, s]) => (
              <tr key={a} className="border-t border-white/[.05] num"><td className="py-1.5 text-slate-200">{a}</td><td>{s.n}</td><td>{s.brier ?? "—"}</td><td>{s.log_loss ?? "—"}</td>
                <td>{s.directional_accuracy != null ? `${pct(s.directional_accuracy, 0)} (${s.directional_ci95?.map((x) => pct(x, 0)).join("–")})` : "—"}</td><td>{s.brier_skill ?? "—"}</td></tr>))}</tbody></table>)}
        <p className="t-micro mt-3">{data.rules}. Kalibratie pas vanaf 30 afgerekende voorspellingen. Uitkomsten dienen alleen om te scoren, nooit om strategieën te kiezen op de beschermde holdout.</p>
      </Panel>
      <Panel title={`Register · ${data.items.length}`}>
        {!data.items.length ? <Empty>Nog geen voorspellingen. Elke afgeronde onderzoeksopdracht registreert een basiskans en, als een AI-analist een kans gaf, ook die.</Empty> : (
          <ul className="divide-y divide-white/[.05] text-[12.5px]">{data.items.map((p) => (
            <li key={p.pid} className="grid gap-1 py-2 md:grid-cols-[110px_160px_70px_minmax(0,1fr)_90px]">
              <code className="font-mono text-[11px] text-slate-500">{p.pid}</code><span className="text-slate-200">{p.agent}{p.model ? ` · ${p.model}` : ""}</span>
              <span className="num text-slate-100">{pct(p.probability, 0)}</span><span className="text-slate-400">{p.outcome_def.text}{p.amendments ? ` · ${p.amendments} amendement(en)` : ""}</span>
              <span className="t-micro">{p.status}{p.outcome != null ? ` · ${p.outcome ? "ja" : "nee"}` : ""}</span></li>))}</ul>)}
      </Panel>
    </div>
  );
}

// ── Evaluatie ────────────────────────────────────────────────────────────────────────────
interface Bench { cases: { case: string; expected: string | null; found: string[]; hit: boolean | null; false_alarm: boolean | null }[]; planted: number; detected: number; clean: number; false_alarms: number; set_hash: string; caveat: string }
interface Arm { variant: string; runs: number; completed: number; blocked: number; cost_usd: number; cost_per_completed: number | null; median_ms: number | null; mean_supported_claims: number | null; mean_high_findings: number | null; revisions_fixed: number }
interface EvalData { challenger_benchmark: Bench; arms: { run: string; at: string; cap_usd: number; spent_usd: number; arms: Record<string, Arm> } | null; reviews: { arms: Record<string, { variant: string; n: number; mean_usefulness: number | null; ci95: number[] | null; errors_found: number }>; total: number; rule: string } }
interface ReviewItem { workflow_id: number; subject: string; question: string; conclusion: Conclusion }

function Evaluation({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const { data, loading, error, refresh } = useApi<EvalData>("/api/genesis/eval", 120_000);
  const [cap, setCap] = useState("0");
  const [item, setItem] = useState<ReviewItem | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  async function next() {
    setErr(null);
    try { setItem((await api<{ item: ReviewItem | null }>("/api/genesis/review/next", { headers: { Authorization: `Bearer ${admin.token}` } })).item); }
    catch (e) { setErr(e instanceof Error ? e.message : "laden mislukt"); }
  }
  if (loading && !data) return <Skeleton className="h-96" />;
  if (error) return <ErrorBox message={error} onRetry={refresh} />;
  if (!data) return null;
  const b = data.challenger_benchmark;
  return (
    <div className="space-y-5">
      <Panel title="Vangt de uitdager fouten? (geplante fouten)" action={<span className="chip">set {b.set_hash}</span>}>
        <p className="text-[13px] text-slate-200"><span className="num">{b.detected}/{b.planted}</span> geplante fouten gevonden · <span className="num">{b.false_alarms}/{b.clean}</span> vals alarm op schone analyses.</p>
        <p className="t-micro mt-1 text-amber-200">Let op: {b.caveat}.</p>
        <ul className="mt-3 grid gap-1 text-[12px] md:grid-cols-2">{b.cases.map((x) => <li key={x.case} className="flex gap-2"><StatusDot status={x.hit === false || x.false_alarm ? "down" : "ok"} /><span className="text-slate-300">{x.case}</span><span className="t-micro">{x.expected ?? "schoon"} → {x.found.join(", ") || "niets"}</span></li>)}</ul>
      </Panel>
      <Panel title="Vergelijking A · B · C · D" action={<div className="flex items-center gap-2"><label className="t-micro" htmlFor="cap">grens $</label>
        <input id="cap" value={cap} onChange={(e) => setCap(e.target.value)} inputMode="decimal" className="w-16 rounded-md border border-white/[.08] bg-white/[.02] px-2 py-1 text-[12.5px] text-slate-200" />
        <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/genesis/eval/arms", { cap_usd: Number(cap) || 0 }, () => refresh())}>Draaien (admin)</Btn></div>}>
        {!data.arms ? <Empty>Nog geen vergelijking gedraaid. Met grens $0 draait alleen A; B–D worden dan eerlijk als geblokkeerd geteld.</Empty> : (
          <table className="w-full text-[12.5px]"><thead><tr className="t-label text-left"><th className="py-1.5">Variant</th><th>runs</th><th>klaar</th><th>geblokkeerd</th><th>kosten/klaar</th><th>mediaan</th><th>onderbouwd</th><th>ernstig</th><th>hersteld</th></tr></thead>
            <tbody>{Object.entries(data.arms.arms).map(([k, a]) => (
              <tr key={k} className="num border-t border-white/[.05]"><td className="py-1.5 text-slate-200">{a.variant} · {k}</td><td>{a.runs}</td><td>{a.completed}</td><td>{a.blocked}</td>
                <td>{a.cost_per_completed != null ? `$${num(a.cost_per_completed, 4)}` : "—"}</td><td>{a.median_ms != null ? `${a.median_ms} ms` : "—"}</td><td>{a.mean_supported_claims ?? "—"}</td><td>{a.mean_high_findings ?? "—"}</td><td>{a.revisions_fixed}</td></tr>))}</tbody></table>)}
        {data.arms && <p className="t-micro mt-2">Run {data.arms.run} · {ago(data.arms.at)} · grens ${num(data.arms.cap_usd, 2)} · besteed ${num(data.arms.spent_usd, 4)}. De eenvoudigste variant wint tenzij een complexere aantoonbaar beter is.</p>}
      </Panel>
      <Panel title={`Blinde beoordeling door de CEO · ${data.reviews.total}`} action={<Btn disabled={!admin.token} onClick={next}>Volgende conclusie</Btn>}>
        <table className="mb-3 w-full text-[12.5px]"><thead><tr className="t-label text-left"><th className="py-1">Variant</th><th>n</th><th>bruikbaarheid (1–5)</th><th>95%-CI</th><th>fouten gevonden</th></tr></thead>
          <tbody>{Object.entries(data.reviews.arms).map(([k, a]) => <tr key={k} className="num border-t border-white/[.05]"><td className="py-1 text-slate-200">{a.variant}</td><td>{a.n}</td><td>{a.mean_usefulness ?? "—"}</td><td>{a.ci95?.join(" – ") ?? "—"}</td><td>{a.errors_found}</td></tr>)}</tbody></table>
        <p className="t-micro">{data.reviews.rule}. Je ziet de variant niet tijdens het beoordelen.</p>
        {err && <p className="mt-2 text-[12.5px] text-rose-300">{err}</p>}
        {item === null && <Empty>Niets meer te beoordelen. Eerst een vergelijking draaien.</Empty>}
        {item && <Review item={item} admin={admin} onDone={() => { setItem(undefined); refresh(); }} />}
      </Panel>
    </div>
  );
}

function Review({ item, admin, onDone }: { item: ReviewItem; admin: ReturnType<typeof useAdmin>; onDone: () => void }) {
  const [u, setU] = useState(3);
  const [e, setE] = useState(0);
  const [note, setNote] = useState("");
  const c = item.conclusion;
  return (
    <div className="mt-3 rounded-lg border border-white/[.06] p-3 text-[12.5px]">
      <div className="text-slate-100">{item.subject}: {item.question}</div>
      <p className="mt-2 text-slate-300">{c.main_hypothesis}</p>
      <p className="t-micro mt-1">Aanbeveling: {c.recommendation ? REC[c.recommendation] ?? c.recommendation : "—"} · {c.supporting_evidence?.length ?? 0} onderbouwde beweringen · {c.counterarguments?.length ?? 0} tegenargumenten · {c.disagreements?.length ?? 0} meningsverschillen</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label><span className="t-label">Bruikbaarheid</span><select value={u} onChange={(x) => setU(Number(x.target.value))} className="ml-2 rounded-md border border-white/[.08] bg-[#0F1217] px-2 py-1 text-slate-200">{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select></label>
        <label><span className="t-label">Fouten gevonden</span><input type="number" min={0} max={50} value={e} onChange={(x) => setE(Number(x.target.value))} className="ml-2 w-16 rounded-md border border-white/[.08] bg-white/[.02] px-2 py-1 text-slate-200" /></label>
        <input value={note} maxLength={500} onChange={(x) => setNote(x.target.value)} placeholder="notitie" aria-label="Notitie" className="min-w-0 flex-1 rounded-md border border-white/[.08] bg-white/[.02] px-2 py-1 text-slate-200" />
        <Btn primary disabled={!!admin.busy} onClick={() => admin.post("/api/genesis/review", { workflow_id: item.workflow_id, usefulness: u, errors_found: e, note }, onDone)}>Opslaan</Btn>
      </div>
    </div>
  );
}

// ── Kosten en storingen ──────────────────────────────────────────────────────────────────
interface CostData { usage: Record<string, unknown>; research_tasks: number; research_cost_usd: number; cost_per_task_usd: number | null; useful_conclusions: number; cost_per_useful_conclusion_usd: number | null; useful_definition: string; failed_calls: number; failed_call_cost_usd: number }
interface Failures { workflows: { trace_id: string; subject: string; status: string; mode: string; problems: { step: string; status: string; reason: string | null }[] }[]; ai_calls: { task: string; provider: string; error: string | null; at: string }[]; tasks: { id: number; kind: string; agent: string; error: string | null }[] }

function Costs() {
  const c = useApi<CostData>("/api/genesis/costs", 60_000);
  const f = useApi<Failures>("/api/genesis/failures", 60_000);
  return (
    <div className="space-y-5">
      {c.data ? (
        <KpiStrip cols="grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
          <KpiCell label="Onderzoeksopdrachten" value={c.data.research_tasks} /><KpiCell label="Kosten onderzoek" value={`$${num(c.data.research_cost_usd, 4)}`} />
          <KpiCell label="Per opdracht" value={c.data.cost_per_task_usd != null ? `$${num(c.data.cost_per_task_usd, 4)}` : "—"} />
          <KpiCell label="Per bruikbare conclusie" value={c.data.cost_per_useful_conclusion_usd != null ? `$${num(c.data.cost_per_useful_conclusion_usd, 4)}` : "—"} sub={`${c.data.useful_conclusions} bruikbaar`} />
          <KpiCell label="Mislukte AI-aanroepen" value={c.data.failed_calls} /><KpiCell label="Kosten mislukte aanroepen" value={`$${num(c.data.failed_call_cost_usd, 4)}`} />
        </KpiStrip>) : c.error ? <ErrorBox message={c.error} onRetry={c.refresh} /> : <Skeleton className="h-24" />}
      {c.data && <p className="t-micro">Bruikbaar = {c.data.useful_definition}.</p>}
      <Panel title="Mislukte of geblokkeerde opdrachten">
        {!f.data?.workflows.length ? <Empty>Geen mislukte of geblokkeerde opdrachten.</Empty> : (
          <ul className="divide-y divide-white/[.05] text-[12.5px]">{f.data.workflows.map((w) => (
            <li key={w.trace_id} className="py-2"><Link href={`/research?trace=${w.trace_id}`} className="text-slate-100 hover:text-cyan-300">{w.subject} · {w.mode} · {w.status}</Link>
              <ul className="t-micro mt-0.5">{w.problems.map((p, i) => <li key={i}>{p.step}: {p.status}{p.reason ? `: ${p.reason}` : ""}</li>)}</ul></li>))}</ul>)}
      </Panel>
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Mislukte AI-aanroepen">{!f.data?.ai_calls.length ? <Empty>Geen.</Empty> : <ul className="space-y-1 text-[12px]">{f.data.ai_calls.map((x, i) => <li key={i} className="text-slate-300">{x.task} · {x.provider} · {x.error} <span className="t-micro">{ago(x.at)}</span></li>)}</ul>}</Panel>
        <Panel title="Mislukte taken">{!f.data?.tasks.length ? <Empty>Geen.</Empty> : <ul className="space-y-1 text-[12px]">{f.data.tasks.map((x) => <li key={x.id} className="text-slate-300">#{x.id} {x.kind} · {x.agent} · {x.error}</li>)}</ul>}</Panel>
      </div>
    </div>
  );
}

// ── Gereedheid ───────────────────────────────────────────────────────────────────────────
const ROLE_DOT: Record<string, string> = { CONNECTED: "ok", TESTED: "ok", IMPLEMENTED: "degraded", BLOCKED: "not_configured" };
function ReadinessView({ r, loading, error }: { r: Readiness | null; loading: boolean; error: string | null }) {
  if (loading && !r) return <Skeleton className="h-96" />;
  if (error) return <ErrorBox message={error} />;
  if (!r) return null;
  return (
    <div className="space-y-5">
      <KpiStrip cols="grid-cols-2 md:grid-cols-4">
        <KpiCell label="Dagbudget AI" value={`$${num(r.budget.daily_usd, 2)}`} sub={`over: $${num(r.budget.left_usd, 4)}`} />
        <KpiCell label="Maximum per opdracht" value={`$${num(r.budget.max_run_usd, 2)}`} />
        <KpiCell label="AI-aanbieders bruikbaar" value={`${r.ai.filter((a) => a.usable).length}/${r.ai.length}`} />
        <KpiCell label="Live handelen" value={r.live_trading ? "aan" : "uit"} />
      </KpiStrip>
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="AI Gateway (geen sleutels, alleen status)">
          <ul className="space-y-1.5 text-[12.5px]">{r.ai.map((a) => <li key={a.provider} className="flex flex-wrap items-center gap-2"><StatusDot status={a.usable ? "ok" : "not_configured"} /><span className="w-20 text-slate-200">{a.provider}</span><span className="text-slate-400">{a.usable ? a.model : a.reason}</span>{a.price_per_mtok_usd && <span className="t-micro ml-auto">${a.price_per_mtok_usd.input}/${a.price_per_mtok_usd.output} per MTok</span>}</li>)}</ul>
        </Panel>
        <Panel title="Databronnen">
          <ul className="space-y-1.5 text-[12.5px]">{r.providers.map((p) => <li key={p.key} className="flex flex-wrap items-center gap-2"><StatusDot status={p.state === "CONNECTED" ? "ok" : p.state === "DEGRADED" || p.state === "SIMULATED" ? "degraded" : p.state === "DISCONNECTED" ? "down" : "not_configured"} /><span className="text-slate-200">{p.name}</span><span className="t-micro">{p.state}{p.last_failure_class ? ` · ${p.last_failure_class}` : ""}{p.missing_env.length ? ` · ontbreekt: ${p.missing_env.join(", ")}` : ""}</span></li>)}</ul>
          <p className="t-micro mt-3">Verbindingen testen en sleutels toevoegen: <Link href="/operations" className="text-cyan-300">Provider Control Center</Link>.</p>
        </Panel>
      </div>
      <Panel title={`Rollen · ${r.roles.length}`} action={<span className="t-micro">status uit wat er echt is gebeurd, niet uit de configuratie</span>}>
        <ul className="grid gap-1.5 text-[12.5px] sm:grid-cols-2 xl:grid-cols-3">{r.roles.map((x) => <li key={x.key} className="flex items-center gap-2"><StatusDot status={ROLE_DOT[x.status] ?? "down"} /><span className="text-slate-200">{x.name}</span><span className="t-micro ml-auto">{x.code_status ? `code ${x.code_status}` : ""}{x.code_status && x.ai_status ? " · " : ""}{x.ai_status ? `AI ${x.ai_status}` : ""}{!x.code_status && !x.ai_status ? x.status : ""}</span></li>)}</ul>
      </Panel>
    </div>
  );
}
