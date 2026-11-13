"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { ago, num } from "@/lib/format";
import { Drawer, Provenance, Tabs } from "./ds";
import type { Org, OrgRole } from "./NeuralCore";
import { DataBadge, Empty, Skeleton, StatusDot } from "./ui";

interface Handoffs { edges: { from: string; to: string; n: number }[]; simulated_traces: number; escalations_open: number; disagreements: number; completed_7d: number }
interface Dossier extends OrgRole {
  task_counts: Record<string, number>; cost_usd: number; pending: OrgRole["open_tasks"];
  workflow_steps: { trace_id: string; workflow_id: number; step: string; status: string; at: string; simulated: boolean }[];
  debates: { id: number; subject: string; status: string; author: string | null; challenger: string | null; recommendation: string | null }[];
  ai_usage: { provider: string; calls: number; cost_usd: number }[]; note: string;
}

const DEPTS: [string, string][] = [["leadership", "Leiding"], ["research", "Research"], ["intelligence", "Market Intelligence"],
  ["operations", "Trading Operations"], ["risk", "Risk & Oversight"], ["learning", "Learning"]];
const KIND: Record<string, string> = { human: "mens", coordinator: "coördinator", llm: "taalmodel via AI Gateway", deterministic: "vaste code" };
const W = 760, H = 560, CX = W / 2, CY = H / 2, R = 205;

function heat(ts: string | null, now: number) {
  if (!ts || !now) return 0;
  const h = (now - new Date(ts).getTime()) / 3.6e6;
  return h <= 1 ? 1 : h <= 24 ? 0.7 : h <= 24 * 7 ? 0.35 : 0.15;
}

/**
 * Neural Core 2.0: de organisatie als netwerk. Afdelingen zijn sectoren rond NEXUS Central; lijnen tussen
 * rollen zijn échte overdrachten uit gebeurtenis-sporen (dikte = aantal). Niets beweegt zonder activiteit.
 * Een klik opent het dossier van de rol. Lijstweergave is het toegankelijke alternatief.
 */
export function NeuralGraph() {
  const org = useApi<Org>("/api/central/org", 30_000);
  const hand = useApi<Handoffs>("/api/hq/handoffs", 60_000);
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [view, setView] = useState<"graph" | "list">("graph");
  const now = org.updatedAt?.getTime() ?? 0;

  const layout = useMemo(() => {
    if (!org.data) return null;
    const roles = org.data.roles.filter((r) => r.key !== "cio");
    const groups = DEPTS.map(([d]) => roles.filter((r) => r.department === d)).filter((g) => g.length);
    const total = roles.length, gap = 0.16;
    const span = Math.PI * 2 - gap * groups.length;
    let a = -Math.PI / 2 + gap / 2;
    const pos: Record<string, { x: number; y: number; a: number; r: OrgRole }> = {};
    const arcs: { d: string; a0: number; a1: number }[] = [];
    for (const g of groups) {
      const a0 = a;
      g.forEach((r, i) => {
        const ang = a + (span / total) * (i + 0.5);
        pos[r.key] = { x: CX + Math.cos(ang) * R, y: CY + Math.sin(ang) * R, a: ang, r };
      });
      a += (span / total) * g.length;
      arcs.push({ d: g[0].department, a0, a1: a });
      a += gap;
    }
    const cio = org.data.roles.find((r) => r.key === "cio");
    if (cio) pos.cio = { x: CX, y: CY, a: 0, r: cio };
    return { pos, arcs };
  }, [org.data]);

  if (org.loading && !org.data) return <Skeleton className="h-[560px]" />;
  if (!org.data || !layout) return <Empty>Organisatie niet te laden.</Empty>;
  const { pos, arcs } = layout;
  const edges = (hand.data?.edges ?? []).filter((e) => pos[e.from] && pos[e.to]);
  const maxN = Math.max(1, ...edges.map((e) => e.n));
  const focus = hover ?? sel;
  const linked = new Set(edges.filter((e) => e.from === focus || e.to === focus).flatMap((e) => [e.from, e.to]));
  const active = org.data.roles.filter((r) => heat(r.last_activity, now) >= 0.7).length;
  const simOnly = hand.data && hand.data.simulated_traces > 0;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
        <Tabs label="Weergave" value={view} onChange={setView} items={[["graph", "Netwerk"], ["list", "Lijst"]]} />
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{active}</b> van {org.data.roles.length} rollen actief in 24 uur</span>
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{edges.reduce((n, e) => n + e.n, 0)}</b> overdrachten</span>
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{hand.data?.disagreements ?? 0}</b> meningsverschillen</span>
        <span className="text-slate-400"><b className="num font-medium text-amber-200">{hand.data?.escalations_open ?? 0}</b> escalaties open</span>
        <span className="text-slate-400"><b className="num font-medium text-slate-100">{hand.data?.completed_7d ?? 0}</b> taken afgerond (7 d)</span>
        {simOnly && <span className="flex items-center gap-1.5 text-slate-500"><DataBadge label="SIMULATED" />{hand.data!.simulated_traces} spoor gebaseerd op een fixture</span>}
      </div>

      {view === "graph" ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
          <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-[860px]" role="group" aria-label="Netwerk van de NEXUS-organisatie">
            <defs>
              <radialGradient id="ng-core" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="#B4DEF8" stopOpacity=".22" /><stop offset="100%" stopColor="#B4DEF8" stopOpacity="0" />
              </radialGradient>
            </defs>
            {/* afdelingssectoren */}
            {arcs.map(({ d, a0, a1 }) => {
              const r0 = R - 24, p0 = [CX + Math.cos(a0) * r0, CY + Math.sin(a0) * r0], p1 = [CX + Math.cos(a1) * r0, CY + Math.sin(a1) * r0];
              const mid = (a0 + a1) / 2, lr = R - 62;
              const lx = CX + Math.cos(mid) * lr, ly = CY + Math.sin(mid) * lr;
              return (
                <g key={d}>
                  <path d={`M${p0[0]},${p0[1]} A${r0},${r0} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${p1[0]},${p1[1]}`} fill="none" stroke="rgba(185,194,207,.18)" strokeWidth="1" />
                  <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle"
                    className="fill-slate-500 text-[9px] uppercase tracking-[0.12em]">{DEPTS.find((x) => x[0] === d)?.[1]}</text>
                </g>
              );
            })}
            {/* spaken naar Central: alleen helder bij recente activiteit */}
            {Object.values(pos).filter((p) => p.r.key !== "cio").map((p) => {
              const h = heat(p.r.last_activity, now);
              return <line key={`s-${p.r.key}`} x1={CX} y1={CY} x2={p.x} y2={p.y} stroke={h >= 0.7 ? "rgba(140,203,242,.28)" : "rgba(255,255,255,.04)"} strokeWidth="1" />;
            })}
            {/* echte overdrachten */}
            {edges.map((e) => {
              const a = pos[e.from], b = pos[e.to];
              const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
              const cx = mx + (CX - mx) * 0.55, cy = my + (CY - my) * 0.55;
              const on = !focus || e.from === focus || e.to === focus;
              return (
                <path key={`${e.from}-${e.to}`} d={`M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`} fill="none"
                  stroke={simOnly ? "#BEB4F0" : "#8CCBF2"} strokeOpacity={on ? 0.75 : 0.12} strokeWidth={1 + (e.n / maxN) * 2.5}
                  strokeDasharray={simOnly ? "4 4" : undefined} style={{ transition: "stroke-opacity 240ms" }}>
                  <title>{`${e.from} → ${e.to}: ${e.n}×`}</title>
                </path>
              );
            })}
            <circle cx={CX} cy={CY} r="70" fill="url(#ng-core)" />
            {Object.values(pos).map(({ x, y, a, r }) => {
              const isC = r.key === "cio";
              const h = heat(r.last_activity, now);
              const dim = focus && focus !== r.key && !linked.has(r.key);
              const err = r.errors.length > 0, open = r.open_tasks.length;
              const rad = isC ? 32 : 8 + Math.min(6, open * 2);
              const lx = CX + Math.cos(a) * (R + 16), ly = CY + Math.sin(a) * (R + 16);
              return (
                <g key={r.key} role="button" tabIndex={0} aria-label={`${r.name}: ${r.last_activity ? `actief ${ago(r.last_activity)}` : "nog geen activiteit"}, ${open} open taken${err ? ", met fouten" : ""}`}
                  onClick={() => setSel(r.key)} onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(r.key)} onBlur={() => setHover(null)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(r.key))}
                  className="cursor-pointer outline-none" style={{ opacity: dim ? 0.3 : 1, transition: "opacity 240ms" }}>
                  <circle cx={x} cy={y} r={rad} fill={isC ? "#101318" : h ? `rgba(140,203,242,${0.12 + h * 0.55})` : "#0B0D11"}
                    stroke={err ? "#E25A64" : sel === r.key ? "#D3ECFB" : isC ? "rgba(180,222,248,.55)" : "rgba(185,194,207,.35)"} strokeWidth={sel === r.key ? 2 : 1} />
                  {open > 0 && !isC && <circle cx={x + rad * 0.75} cy={y - rad * 0.75} r="3" fill="#DDB25C" />}
                  {isC ? (
                    <>
                      <text x={CX} y={CY - 2} textAnchor="middle" className="fill-slate-100 text-[11px] font-semibold tracking-[0.16em]">NEXUS</text>
                      <text x={CX} y={CY + 12} textAnchor="middle" className="fill-slate-500 text-[9px]">Central</text>
                    </>
                  ) : (
                    <text x={lx} y={ly} textAnchor={Math.abs(Math.cos(a)) < 0.2 ? "middle" : Math.cos(a) > 0 ? "start" : "end"} dominantBaseline="middle"
                      className={`text-[10.5px] ${sel === r.key || hover === r.key ? "fill-white" : h >= 0.7 ? "fill-slate-300" : "fill-slate-500"}`}>{r.name}</text>
                  )}
                </g>
              );
            })}
          </svg>
          <aside className="space-y-4 text-[12.5px]">
            <div>
              <div className="t-label mb-2">Legenda</div>
              <ul className="space-y-1.5 text-slate-400">
                <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[rgba(140,203,242,.67)]" />actief in het laatste uur (fel) of 24 uur</li>
                <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border border-slate-500" />geen recente activiteit</li>
                <li className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-amber-400" />open taak</li>
                <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border border-rose-500" />fout in een recente taak</li>
                <li className="flex items-center gap-2"><span className="h-0.5 w-5 bg-cyan-300" />overdracht in een gebeurtenis-spoor (dikte = aantal)</li>
                <li className="flex items-center gap-2"><span className="h-0 w-5 border-t border-dashed border-violet-300" />alleen uit een gesimuleerd spoor</li>
              </ul>
            </div>
            <p className="t-micro leading-relaxed">Elke lijn en elke kleur komt uit opgeslagen taken en sporen. Er wordt geen activiteit nagebootst; zonder werk staat het netwerk stil. Klik een rol voor het dossier.</p>
          </aside>
        </div>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {DEPTS.map(([d, name]) => (
            <section key={d}>
              <div className="eyebrow mb-2">{name}</div>
              <ul className="divide-y divide-white/[.05] text-[13px]">
                {org.data!.roles.filter((r) => r.department === d).map((r) => (
                  <li key={r.key}>
                    <button onClick={() => setSel(r.key)} className="flex w-full items-center justify-between gap-2 py-2 text-left hover:text-white">
                      <span className="flex items-center gap-2"><StatusDot status={r.errors.length ? "down" : heat(r.last_activity, now) >= 0.7 ? "ok" : "disabled"} /><span className="text-slate-200">{r.name}</span></span>
                      <span className="t-micro">{r.open_tasks.length ? `${r.open_tasks.length} open · ` : ""}{r.last_activity ? ago(r.last_activity) : "geen activiteit"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <AgentDrawer roleKey={sel} onClose={() => setSel(null)} />
    </div>
  );
}

function AgentDrawer({ roleKey, onClose }: { roleKey: string | null; onClose: () => void }) {
  const { data } = useApi<Dossier>(roleKey ? `/api/hq/agents/${roleKey}` : null, 60_000);
  const d = data && data.key === roleKey ? data : null;
  return (
    <Drawer open={!!roleKey} onClose={onClose} title={d?.name ?? "Rol"}>
      {!d ? <Skeleton className="h-64" /> : (
        <div className="space-y-5 text-[12.5px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="chip">{d.department_name}</span><span className="chip">{KIND[d.kind] ?? d.kind}</span>
            <Provenance kind={d.kind === "llm" ? "ai" : d.kind === "human" ? "human" : "rule"} />
          </div>
          <p className="text-slate-400">Uitgevoerd door <code className="font-mono text-[11.5px] text-slate-300">{d.backed_by}</code>. Laatste activiteit: {d.last_activity ? ago(d.last_activity) : "nooit"}.</p>
          <dl className="grid grid-cols-3 gap-3">
            <div><dt className="t-label">Open taken</dt><dd className="num mt-0.5 text-slate-100">{d.pending.length}</dd></div>
            <div><dt className="t-label">Kosten (taken)</dt><dd className="num mt-0.5 text-slate-100">${num(d.cost_usd, 3)}</dd></div>
            <div><dt className="t-label">Voorspellingen</dt><dd className="num mt-0.5 text-slate-100">{d.forecasts}</dd></div>
          </dl>
          <Section title="Huidige en open taken">
            {d.pending.length ? d.pending.map((t) => <Row key={t.id} a={`${t.kind} · ${t.status}`} b={t.reason} c={ago(t.created_at)} />) : <None>Geen open taken.</None>}
          </Section>
          <Section title="Recente uitkomsten">
            {d.recent_tasks.length ? d.recent_tasks.map((t) => <Row key={t.id} a={`${t.kind} · ${t.status}`} b={t.reason} c={ago(t.updated_at)} />) : <None>Nog geen afgeronde taken.</None>}
          </Section>
          <Section title="Bijdragen aan gebeurtenis-sporen (bewijs)">
            {d.workflow_steps.length ? d.workflow_steps.map((s, i) => (
              <div key={i} className="flex items-center justify-between gap-2 py-1">
                <span className="text-slate-300">{s.step} · {s.status}{s.simulated && <span className="ml-2"><DataBadge label="SIMULATED" /></span>}</span>
                <Link href={`/decisions?trace=${s.workflow_id}`} className="font-mono text-[11px] text-cyan-300">{s.trace_id}</Link>
              </div>)) : <None>Geen stappen in sporen.</None>}
          </Section>
          {d.debates.length > 0 && (
            <Section title="Debatten">
              {d.debates.map((x) => <Row key={x.id} a={`#${x.id} ${x.status}`} b={x.subject} c={`${x.author ?? "—"} vs ${x.challenger ?? "—"}`} />)}
            </Section>
          )}
          <Section title="Modelaanbieder en AI-gebruik">
            {d.ai_usage.length ? d.ai_usage.map((u) => <Row key={u.provider} a={u.provider} b={`${u.calls} aanroepen`} c={`$${num(u.cost_usd, 3)}`} />)
              : <None>{d.kind === "llm" ? "Nog geen AI-aanroepen: geen aanbieder verbonden." : "Deze rol gebruikt geen taalmodel."}</None>}
          </Section>
          <Section title="Fouten">
            {d.errors.length ? d.errors.map((e) => <Row key={e.id} a={e.kind} b={e.error ?? "fout"} />) : <None>Geen fouten.</None>}
          </Section>
          <p className="t-micro">{d.note}</p>
        </div>
      )}
    </Drawer>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><div className="t-label mb-1.5">{title}</div><div className="divide-y divide-white/[.04]">{children}</div></section>;
}
function Row({ a, b, c }: { a: string; b: string; c?: string }) {
  return <div className="py-1.5"><div className="flex justify-between gap-2"><span className="text-slate-300">{a}</span>{c && <span className="t-micro shrink-0">{c}</span>}</div><div className="text-slate-500">{b}</div></div>;
}
function None({ children }: { children: React.ReactNode }) {
  return <p className="py-1 text-slate-500">{children}</p>;
}
