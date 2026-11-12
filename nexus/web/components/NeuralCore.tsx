"use client";

import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { ago } from "@/lib/format";
import { Empty, Skeleton } from "./ui";

export interface OrgRole {
  key: string; name: string; department: string; department_name: string; kind: string; backed_by: string;
  last_activity: string | null; forecasts: number;
  open_tasks: { id: number; kind: string; status: string; reason: string; created_at: string }[];
  recent_tasks: { id: number; kind: string; status: string; reason: string; updated_at: string; error: string | null }[];
  errors: { id: number; kind: string; error: string | null }[];
}
export interface Org { departments: Record<string, string>; roles: OrgRole[]; ai: { key_present: boolean } }

const DEPT_ORDER = ["leadership", "research", "intelligence", "operations", "risk", "learning"];
const KIND_TEXT: Record<string, string> = { human: "mens", coordinator: "coördinator", llm: "Claude", deterministic: "regels" };

/** Activiteit telt alleen uit echte tijdstempels: ≤ 1 uur fel, ≤ 24 uur rustig, ouder gedimd, nooit = open ring. */
function heat(ts: string | null, now: number): number {
  if (!ts) return 0;
  const h = (now - new Date(ts).getTime()) / 3.6e6;
  return h <= 1 ? 1 : h <= 24 ? 0.7 : h <= 24 * 7 ? 0.4 : 0.2;
}

export function NeuralCore({ compact = false, onSelect }: { compact?: boolean; onSelect?: (r: OrgRole) => void }) {
  const { data, loading, error, updatedAt } = useApi<Org>("/api/central/org", 30_000);
  const [sel, setSel] = useState<string | null>(null);
  const now = updatedAt?.getTime() ?? 0;   // ophaalmoment: geen klok tijdens het prerenderen
  const layout = useMemo(() => {
    if (!data) return null;
    const roles = DEPT_ORDER.flatMap((d) => data.roles.filter((r) => r.department === d && r.key !== "cio"));
    const n = roles.length;
    return roles.map((r, i) => {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2;
      return { r, x: 200 + Math.cos(a) * 150, y: 200 + Math.sin(a) * 150, a };
    });
  }, [data]);
  if (loading && !data) return <Skeleton className="h-[360px]" />;
  if (error && !data) return <Empty>Organisatie niet te laden: {error}</Empty>;
  if (!data || !layout) return null;
  const cio = data.roles.find((r) => r.key === "cio");
  const pick = (r: OrgRole) => { setSel(r.key); onSelect?.(r); };
  const chosen = data.roles.find((r) => r.key === sel) ?? null;
  const active = data.roles.filter((r) => heat(r.last_activity, now) >= 0.7).length;

  return (
    <div className={compact ? "" : "grid gap-6 lg:grid-cols-[minmax(0,560px)_1fr]"}>
      <figure className="relative">
        <svg viewBox={compact ? "0 0 400 400" : "-90 0 580 400"} className={`mx-auto w-full ${compact ? "max-w-[420px]" : "max-w-[560px]"}`} role="group" aria-label="NEXUS-organisatie: agents rond NEXUS Central">
          <defs>
            <radialGradient id="core" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#B4DEF8" stopOpacity=".35" /><stop offset="100%" stopColor="#B4DEF8" stopOpacity="0" />
            </radialGradient>
          </defs>
          <circle cx="200" cy="200" r="150" fill="none" stroke="rgba(255,255,255,.05)" />
          <circle cx="200" cy="200" r="95" fill="none" stroke="rgba(255,255,255,.035)" strokeDasharray="2 6" />
          {layout.map(({ r, x, y }) => {
            const h = heat(r.last_activity, now);
            return (
              <line key={`l-${r.key}`} x1="200" y1="200" x2={x} y2={y}
                stroke={h >= 0.7 ? "rgba(140,203,242,.55)" : "rgba(255,255,255,.06)"} strokeWidth={h >= 0.7 ? 1.2 : 1}
                className={h >= 0.7 ? "flow" : ""} />
            );
          })}
          <circle cx="200" cy="200" r="60" fill="url(#core)" className={cio && heat(cio.last_activity, now) >= 0.7 ? "breathe" : ""} />
          <circle cx="200" cy="200" r="30" fill="#101318" stroke="rgba(180,222,248,.5)" />
          <text x="200" y="197" textAnchor="middle" className="fill-slate-100 text-[10px] font-semibold tracking-[0.14em]">NEXUS</text>
          <text x="200" y="210" textAnchor="middle" className="fill-slate-500 text-[8px]">Central</text>
          {layout.map(({ r, x, y, a }) => {
            const h = heat(r.last_activity, now);
            const isSel = sel === r.key;
            const lx = 200 + Math.cos(a) * 178, ly = 200 + Math.sin(a) * 178;
            const anchor = Math.abs(Math.cos(a)) < 0.25 ? "middle" : Math.cos(a) > 0 ? "start" : "end";
            return (
              <g key={r.key} role="button" tabIndex={0} aria-label={`${r.name}, ${r.last_activity ? `actief ${ago(r.last_activity)}` : "nog geen activiteit"}`}
                onClick={() => pick(r)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick(r))}
                className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-cyan-300">
                <circle cx={x} cy={y} r={isSel ? 9 : 7} fill={h ? `rgba(140,203,242,${0.15 + h * 0.6})` : "#0B0D11"}
                  stroke={h ? "rgba(180,222,248,.9)" : "rgba(255,255,255,.22)"} strokeWidth={isSel ? 2 : 1} />
                {r.open_tasks.length > 0 && <circle cx={x + 6} cy={y - 6} r="2.6" fill="#DDB25C" />}
                {r.errors.length > 0 && <circle cx={x - 6} cy={y - 6} r="2.6" fill="#E25A64" />}
                {!compact && <text x={lx} y={ly + 3} textAnchor={anchor} className={`text-[8.5px] ${isSel ? "fill-white" : "fill-slate-400"}`}>{r.name.replace(/ \(.*\)/, "")}</text>}
              </g>
            );
          })}
        </svg>
        <figcaption className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
          <span>{active} van {data.roles.length} actief in 24 uur</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" />open taak</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-rose-500" />fout</span>
          <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full border border-slate-500" />nog geen activiteit</span>
        </figcaption>
      </figure>
      {!compact && (
        <div className="min-w-0">
          {chosen ? <RoleDetail r={chosen} /> : (
            <div className="space-y-4">
              {DEPT_ORDER.map((d) => (
                <div key={d}>
                  <div className="eyebrow mb-1.5">{data.departments[d]}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.roles.filter((r) => r.department === d).map((r) => (
                      <button key={r.key} onClick={() => pick(r)}
                        className="rounded-md border border-white/[.07] px-2.5 py-1 text-[12.5px] text-slate-300 transition-colors hover:border-white/20 hover:text-white">
                        {r.name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <p className="text-[12px] leading-relaxed text-slate-500">Kies een rol voor taken, recente uitkomsten en fouten. Activiteit komt alleen uit echte gebeurtenissen in de database; zonder Claude-sleutel draaien de taalmodel-rollen niet.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function RoleDetail({ r }: { r: OrgRole }) {
  return (
    <div className="fade-up space-y-4">
      <div>
        <div className="eyebrow">{r.department_name}</div>
        <h3 className="mt-1 text-lg font-semibold text-white">{r.name}</h3>
        <div className="mt-1 text-[12.5px] text-slate-400">{KIND_TEXT[r.kind] ?? r.kind} · {r.backed_by}</div>
      </div>
      <dl className="grid grid-cols-3 gap-3 text-[12.5px]">
        <div><dt className="caption">Laatst actief</dt><dd className="mt-0.5 text-slate-200">{r.last_activity ? ago(r.last_activity) : "nog nooit"}</dd></div>
        <div><dt className="caption">Voorspellingen</dt><dd className="num mt-0.5 text-slate-200">{r.forecasts}</dd></div>
        <div><dt className="caption">Open taken</dt><dd className="num mt-0.5 text-slate-200">{r.open_tasks.length}</dd></div>
      </dl>
      <TaskList title="Open taken" items={r.open_tasks.map((t) => ({ id: t.id, text: t.reason, meta: `${t.kind} · ${t.status}` }))} />
      <TaskList title="Recent afgerond" items={r.recent_tasks.map((t) => ({ id: t.id, text: t.reason, meta: `${t.kind} · ${t.status}${t.error ? ` · ${t.error}` : ""}` }))} />
      {r.errors.length > 0 && <TaskList title="Fouten" items={r.errors.map((t) => ({ id: t.id, text: t.error ?? "", meta: t.kind }))} />}
    </div>
  );
}

function TaskList({ title, items }: { title: string; items: { id: number; text: string; meta: string }[] }) {
  return (
    <div>
      <div className="eyebrow mb-1.5">{title}</div>
      {items.length === 0 ? <div className="text-[12.5px] text-slate-600">Geen.</div> : (
        <ul className="divide-y divide-white/[.05]">
          {items.slice(0, 6).map((t) => (
            <li key={t.id} className="py-1.5 text-[12.5px]"><div className="text-slate-200">{t.text}</div><div className="text-slate-500">#{t.id} · {t.meta}</div></li>
          ))}
        </ul>
      )}
    </div>
  );
}
