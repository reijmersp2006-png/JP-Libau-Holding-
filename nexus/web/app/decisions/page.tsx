"use client";

import { safeUrl } from "@/lib/url";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageHeader, Provenance } from "@/components/ds";
import { DataBadge, Empty, Panel, Skeleton, StatusDot } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, num, pct } from "@/lib/format";

interface Step { step: string; agent: string; status: string; at: string; ms?: number | null; detail: Record<string, unknown> }
interface Wf {
  id: number; trace_id: string; news_id: number; status: string; simulated: boolean; source: string; title: string; url: string;
  published_at: string; detected_at: string; finished_at: string | null; cost_usd: number; steps: Step[];
  intelligence: { confirmed: string; missing: string[]; research_priority: string; enough_evidence_for_research: boolean; evidence_note: string; assets: string[] };
}

type Kind = "measured" | "ai" | "rule" | "human" | "simulated";
interface Stage { key: string; name: string; agent: string; steps: string[]; kind: Kind; limitation: string }
const STAGES: Stage[] = [
  { key: "event", name: "Marktgebeurtenis", agent: "News Analyst", steps: ["validate", "deduplicate"], kind: "rule", limitation: "Alleen bronnen met een toegestane feed; tijdstempel van de bron wordt gecontroleerd, niet geloofd." },
  { key: "intel", name: "Nieuws- en social-intelligence", agent: "News / Social", steps: ["classify", "social"], kind: "rule", limitation: "Classificatie met vaste regels; X is niet verbonden, dus sociale context ontbreekt meestal." },
  { key: "ai", name: "AI-analyse", agent: "Crypto Analyst", steps: ["research"], kind: "ai", limitation: "Een mening van een taalmodel, alleen met verwijzingen naar feiten. Geen bewijs op zich." },
  { key: "challenge", name: "Onafhankelijke uitdaging", agent: "Strategy Auditor", steps: ["challenge"], kind: "ai", limitation: "Alleen onafhankelijk als een andere aanbieder uitdaagt dan de auteur." },
  { key: "quant", name: "Kwantitatieve toets", agent: "Quant Researcher", steps: ["market", "quant"], kind: "measured", limitation: "Event study vanaf 8 gelijksoortige gebeurtenissen; vertraagde dagkoersen; spread ontbreekt." },
  { key: "risk", name: "Risicobeoordeling", agent: "Risk Guardian", steps: ["risk"], kind: "rule", limitation: "Nieuws leidt nooit direct tot een order; limieten en live-status veranderen niet." },
  { key: "ceo", name: "CEO-besluit", agent: "Founder / CEO", steps: ["central", "explain"], kind: "human", limitation: "Central geeft een onderzoeksprioriteit, geen handelsadvies. Escalatie alleen bij een onderbouwd voorstel." },
  { key: "exec", name: "Goedgekeurde uitvoering", agent: "Execution Specialist", steps: [], kind: "rule", limitation: "Live handelen staat uit. Alleen paper, en alleen na Risk Guardian en CEO." },
  { key: "learn", name: "Leer-evaluatie", agent: "Model Evaluation", steps: [], kind: "measured", limitation: "Afrekenen gebeurt pas na de vooraf vastgelegde horizon." },
];
const OK = new Set(["ok", "duplicate"]);
const DOT: Record<string, string> = { ok: "ok", warning: "degraded", duplicate: "disabled", not_applicable: "disabled", unavailable: "not_configured", skipped: "not_configured", none: "disabled" };

function stageState(st: Stage, w: Wf): { status: string; steps: Step[] } {
  const steps = w.steps.filter((s) => st.steps.includes(s.step));
  if (!st.steps.length) return { status: "none", steps };
  if (!steps.length) return { status: w.steps.some((s) => s.status === "duplicate") ? "not_applicable" : "none", steps };
  if (steps.some((s) => s.status === "warning")) return { status: "warning", steps };
  if (steps.every((s) => OK.has(s.status) || s.status === "not_applicable")) return { status: steps.some((s) => OK.has(s.status)) ? "ok" : "not_applicable", steps };
  return { status: steps.find((s) => !OK.has(s.status))!.status, steps };
}

function fmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) < 1 && v !== 0 ? num(v, 4) : num(v, 2);
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "ja" : "nee";
  return JSON.stringify(v).slice(0, 220);
}

export default function Page() {
  const { data, loading } = useApi<{ items: Wf[]; total: number }>("/api/workflows?limit=50", 60_000);
  const [sel, setSel] = useState<number | null>(null);
  const [stage, setStage] = useState<string>("event");
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("trace");
    if (t) { const id = Number(t); const h = setTimeout(() => setSel(id), 0); return () => clearTimeout(h); }
  }, []);
  const w = useMemo(() => data?.items.find((x) => x.id === sel) ?? data?.items[0], [data, sel]);

  return (
    <div className="page-in">
      <PageHeader eyebrow="AI-organisatie" title="Decision Theater"
        sub="Elke gebeurtenis van bron tot besluit: wie deed wat, wanneer, op basis van welk bewijs, en wat er ontbreekt. Gemeten resultaten, vaste regels en AI-meningen zijn steeds apart gemarkeerd."
        right={<span className="chip">Live handelen uit · geen order zonder Risk Guardian en CEO</span>} />
      <ResearchTheater />
      {loading && !data ? <Skeleton className="h-[600px]" /> : !data?.items.length ? (
        <Empty>Nog geen gebeurtenis-sporen. Een spoor ontstaat als NEXUS Central een relevant nieuwsbericht verwerkt; zonder bereikbare feeds blijft dit leeg.</Empty>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
          <Panel title={`Sporen · ${data.total}`} className="!p-3 xl:self-start">
            <ul className="space-y-1">
              {data.items.map((x) => (
                <li key={x.id}><button onClick={() => setSel(x.id)} aria-current={w?.id === x.id}
                  className={`w-full rounded-md px-2.5 py-2 text-left text-[12.5px] ${w?.id === x.id ? "bg-white/[.06]" : "hover:bg-white/[.03]"}`}>
                  <div className="line-clamp-2 text-slate-200">{x.title}</div>
                  <div className="t-micro mt-0.5 flex flex-wrap items-center gap-1.5">{x.source} · {ago(x.published_at)} · {x.intelligence.research_priority}{x.simulated && <DataBadge label="SIMULATED" />}</div>
                </button></li>
              ))}
            </ul>
          </Panel>

          {w && (
            <div className="min-w-0 space-y-5">
              <Panel>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 basis-[28rem]">
                    <div className="flex flex-wrap items-center gap-2"><code className="font-mono text-[11.5px] text-slate-500">{w.trace_id}</code>{w.simulated && <DataBadge label="SIMULATED" />}<span className="chip">{w.status}</span></div>
                    <h2 className="mt-2 text-[17px] font-medium leading-snug text-white">{w.title}</h2>
                    <div className="t-label mt-1.5">{w.source} · gepubliceerd {new Date(w.published_at).toLocaleString("nl-NL")} · binnen {new Date(w.detected_at).toLocaleString("nl-NL")} · <a href={safeUrl(w.url)} target="_blank" rel="noreferrer noopener" className="text-cyan-300">bron</a></div>
                  </div>
                  <div className="shrink-0 text-[12px] lg:text-right"><div className="t-label">Onderzoeksprioriteit</div><div className="t-kpi mt-1">{w.intelligence.research_priority}</div><div className="t-micro">AI-kosten ${num(w.cost_usd, 3)}</div></div>
                </div>

                {/* De beslisketen: negen stappen, horizontaal; klik voor details */}
                <ol className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5 2xl:grid-cols-9" aria-label="Beslisketen">
                  {STAGES.map((st, i) => {
                    const s = stageState(st, w);
                    const reached = s.status !== "none";
                    return (
                      <li key={st.key} className="relative min-w-0">
                        {i > 0 && <span aria-hidden className={`absolute -left-2 top-[18px] hidden h-px w-2 2xl:block ${reached ? "bg-slate-500" : "bg-white/10"}`} />}
                        <button onClick={() => setStage(st.key)} aria-pressed={stage === st.key}
                          className={`w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${stage === st.key ? "border-cyan-300/40 bg-cyan-300/[.06]" : "border-white/[.06] hover:border-white/[.14]"} ${reached ? "" : "opacity-55"}`}>
                          <div className="flex items-center gap-1.5"><StatusDot status={DOT[s.status] ?? "down"} /><span className="num text-[10.5px] text-slate-500">{String(i + 1).padStart(2, "0")}</span></div>
                          <div lang="nl" className="mt-1 text-[12px] leading-tight text-slate-100 [overflow-wrap:anywhere] hyphens-auto">{st.name}</div>
                          <div className="t-micro mt-0.5">{s.status === "none" ? "niet bereikt" : s.status}</div>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </Panel>

              <StageDetail st={STAGES.find((s) => s.key === stage)!} w={w} />

              <Panel title="Wat ontbreekt">
                <ul className="grid gap-1.5 text-[12.5px] md:grid-cols-2">{w.intelligence.missing.map((m) => <li key={m} className="flex gap-2 text-slate-300"><span className="mt-[7px] h-1 w-1 rounded-full bg-amber-300" />{m}</li>)}</ul>
                <p className="t-micro mt-3">Genoeg bewijs voor onderzoek: {w.intelligence.enough_evidence_for_research ? "ja" : "nee"} · {w.intelligence.evidence_note}. Instrumenten: {w.intelligence.assets.join(", ") || "geen"}.</p>
              </Panel>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StageDetail({ st, w }: { st: Stage; w: Wf }) {
  const s = stageState(st, w);
  const conf = s.steps.map((x) => x.detail?.confidence ?? x.detail?.relevance).find((v) => typeof v === "number") as number | undefined;
  return (
    <Panel title={st.name} action={<span className="flex items-center gap-2"><Provenance kind={w.simulated ? "simulated" : st.kind} />{w.simulated && st.kind !== "simulated" && <Provenance kind={st.kind} />}</span>}>
      <dl className="mb-4 grid grid-cols-2 gap-x-6 gap-y-3 text-[12.5px] md:grid-cols-5">
        <div><dt className="t-label">Status</dt><dd className="mt-0.5 text-slate-100">{s.status === "none" ? "niet bereikt" : s.status}</dd></div>
        <div><dt className="t-label">Agent</dt><dd className="mt-0.5 text-slate-100">{st.agent}{s.steps[0] ? ` (${s.steps.map((x) => x.agent).join(", ")})` : ""}</dd></div>
        <div><dt className="t-label">Tijdstip</dt><dd className="num mt-0.5 text-slate-100">{s.steps[0] ? new Date(s.steps[0].at).toLocaleString("nl-NL") : "—"}</dd></div>
        <div><dt className="t-label">Bron</dt><dd className="mt-0.5 text-slate-100">{st.key === "event" ? w.source : st.kind === "ai" ? "AI Gateway" : "NEXUS (vaste code)"}</dd></div>
        <div><dt className="t-label">Zekerheid</dt><dd className="num mt-0.5 text-slate-100">{conf != null ? pct(conf, 0) : "—"}</dd></div>
      </dl>
      {s.steps.length ? (
        <div className="space-y-3">
          {s.steps.map((x) => (
            <div key={x.step} className="rounded-lg border border-white/[.05] p-3">
              <div className="mb-2 flex items-center justify-between text-[12px]"><span className="font-mono text-slate-300">{x.step}</span><span className="t-micro">{x.status}{x.ms != null ? ` · ${x.ms} ms` : ""}</span></div>
              <dl className="grid gap-x-6 gap-y-1.5 text-[12px] md:grid-cols-2">
                {Object.entries(x.detail ?? {}).filter(([k]) => k !== "trail").map(([k, v]) => (
                  <div key={k} className="flex gap-2"><dt className="shrink-0 text-slate-500">{k}</dt><dd className="min-w-0 break-words text-slate-300">{fmt(v)}</dd></div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      ) : <p className="text-[12.5px] text-slate-500">{st.key === "exec" ? "Niet bereikt: dit spoor heeft geen order opgeleverd en live handelen staat uit." : st.key === "learn" ? "Niet bereikt: er is geen besluit om af te rekenen." : "Deze stap is voor dit spoor niet uitgevoerd."}</p>}
      <p className="t-micro mt-4">Beperking: {st.limitation}</p>
      {st.key === "ceo" && <p className="mt-2 text-[12px]"><Link href="/hq#taken" className="text-cyan-300">Takenwachtrij</Link> voor wat op jouw besluit wacht.</p>}
    </Panel>
  );
}

/* Onderzoekssporen (Genesis): elke stap met agent, model, bewijs, tijdstip, besluit, kosten en status. */
interface RRow { trace_id: string; subject: string; variant: string; status: string; created_at: string; cost_usd: number | null; recommendation: string | null; disagreements: number }
interface RStep { step: string; agent: string; status: string; at: string; model: string | null; provider: string | null; evidence: string[]; decision: string | null; cost_usd: number | null }
const RDOT: Record<string, string> = { ok: "ok", done: "ok", partial: "degraded", blocked: "not_configured", skipped: "disabled", not_applicable: "disabled", failed: "down", running: "degraded" };

function ResearchTheater() {
  const list = useApi<{ items: RRow[] }>("/api/research?limit=8", 60_000);
  const [sel, setSel] = useState<string | null>(null);
  const cur = sel ?? list.data?.items[0]?.trace_id ?? null;
  const one = useApi<{ trace_id: string; steps: RStep[] }>(cur ? `/api/research/${encodeURIComponent(cur)}` : null, 60_000);
  if (!list.data?.items.length) return null;
  const steps = one.data?.trace_id === cur ? one.data.steps : [];
  return (
    <Panel title="Onderzoekssporen" className="mb-5" action={<Link href={cur ? `/research?trace=${cur}` : "/research"} className="text-[12px] text-cyan-300">Volledig spoor en conclusie →</Link>}>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {list.data.items.map((x) => (
          <button key={x.trace_id} onClick={() => setSel(x.trace_id)} aria-pressed={cur === x.trace_id}
            className={`chip ${cur === x.trace_id ? "border-cyan-300/40 text-white" : ""}`}><StatusDot status={RDOT[x.status] ?? "down"} />{x.subject} · {x.variant} · {ago(x.created_at)}</button>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[12px]">
          <thead><tr className="t-label text-left"><th className="py-1.5">Stap</th><th>Agent</th><th>Model</th><th>Bewijs</th><th>Tijdstip</th><th>Besluit</th><th className="pr-6 text-right">Kosten</th><th>Status</th></tr></thead>
          <tbody>{steps.map((s, i) => (
            <tr key={i} className="border-t border-white/[.05] align-baseline">
              <td className="py-1.5 font-mono text-slate-200">{s.step}</td><td className="text-slate-300">{s.agent}</td>
              <td className="text-slate-400">{s.model ? `${s.provider} · ${s.model}` : s.status === "blocked" ? "geen aanbieder" : "vaste code"}</td>
              <td className="max-w-[220px] truncate font-mono text-[11px] text-slate-500" title={s.evidence.join(", ")}>{s.evidence.length ? `${s.evidence.length}: ${s.evidence.slice(0, 3).join(", ")}${s.evidence.length > 3 ? " …" : ""}` : "—"}</td>
              <td className="num text-slate-400">{new Date(s.at).toLocaleTimeString("nl-NL")}</td>
              <td className="max-w-[240px] text-slate-300">{s.decision ?? "—"}</td>
              <td className="num pr-6 text-right text-slate-300">{s.cost_usd != null ? `$${num(s.cost_usd, 4)}` : "—"}</td>
              <td><span className="flex items-center gap-1.5"><StatusDot status={RDOT[s.status] ?? "down"} />{s.status}</span></td>
            </tr>))}</tbody>
        </table>
      </div>
    </Panel>
  );
}
