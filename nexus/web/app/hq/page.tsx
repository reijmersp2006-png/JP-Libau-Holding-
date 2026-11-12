"use client";

import { useState } from "react";
import { Btn, useAdmin } from "@/components/admin";
import { BriefingCard } from "@/components/BriefingCard";
import { DecisionFlow } from "@/components/DecisionFlow";
import { NeuralCore } from "@/components/NeuralCore";
import { Empty, PageTitle, Panel, Segmented, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago } from "@/lib/format";

interface Task {
  id: number; kind: string; department: string; agent: string; status: string; priority: number; subject: string | null;
  reason: string; error: string | null; cost_usd: number | null; created_at: string; updated_at: string;
}
interface Answer {
  question: string; topic: string; answer: string; refs: string[]; mode: string; cost_usd: number;
  evidence: { text: string; ref: string; href: string | null }[]; data_gaps: string[]; can_execute: boolean;
}
interface Holdout { contamination: { datasets: string; seen_until: string; prospective_start: string; reason: string }[]; evaluations: number; min_prospective_days: number }

const STATUS_TEXT: Record<string, [string, string]> = {
  queued: ["in de wachtrij", "text-slate-300"], running: ["bezig", "text-cyan-300"], done: ["klaar", "text-emerald-300"],
  failed: ["mislukt", "text-rose-300"], escalated: ["wacht op CEO", "text-amber-300"], cancelled: ["geannuleerd", "text-slate-500"],
};
const EXAMPLES = [
  "Wat zijn de sterkste kansen in het onderzoek?",
  "Waarom is het laatste voorstel afgewezen?",
  "Wat heeft het systeem deze week geleerd?",
  "Welk belangrijk nieuws was er?",
  "Hoe doet Grok het vergeleken met NEXUS?",
  "Wat wacht op mijn goedkeuring?",
];

export default function Page() {
  const admin = useAdmin();
  return (
    <>
      <PageTitle title="AI Headquarters"
        sub="Wie doet wat, waarom, en wat er op jouw besluit wacht. Alles hieronder komt uit echte taken en gebeurtenissen in de database; agents kunnen geen limieten verhogen, regels herschrijven of orders plaatsen."
        right={admin.field} />
      <div className="space-y-5">
        <Panel title="Organisatie" action={<span className="caption">kies een rol voor taken, uitkomsten en fouten</span>}>
          <NeuralCore />
        </Panel>
        <div className="grid gap-5 xl:grid-cols-[1fr_440px]">
          <Copilot admin={admin} />
          <Panel title="Executive briefing" action={<Btn disabled={!admin.token || !!admin.busy}
            onClick={() => admin.post("/api/central/briefing", undefined, () => location.reload())}>Vastleggen</Btn>}>
            <BriefingCard full />
          </Panel>
        </div>
        <Panel title="Live Decision Timeline"><DecisionFlow /></Panel>
        <Tasks admin={admin} />
        <HoldoutStatus />
      </div>
    </>
  );
}

function Copilot({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const [q, setQ] = useState("");
  const [log, setLog] = useState<Answer[]>([]);
  async function ask(question: string) {
    const r = await admin.post<Answer>("/api/copilot/ask", { question });
    if (r) { setLog((l) => [r, ...l].slice(0, 6)); setQ(""); }
  }
  return (
    <Panel title="CEO Copilot" action={<span className="caption">antwoordt met bewijs · kan niets uitvoeren</span>}>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 3) ask(q.trim()); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Stel een vraag over het platform…" aria-label="Vraag aan de Copilot"
          className="min-w-0 flex-1 rounded-md border border-white/[.08] bg-white/[.02] px-3 py-2 text-[13.5px] text-slate-100 placeholder:text-slate-600 focus:border-white/20" />
        <Btn primary disabled={!admin.token || !!admin.busy || q.trim().length < 3} onClick={() => ask(q.trim())}>Vraag</Btn>
      </form>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {EXAMPLES.map((e) => (
          <button key={e} disabled={!admin.token || !!admin.busy} onClick={() => ask(e)}
            className="rounded-full border border-white/[.07] px-2.5 py-1 text-[12px] text-slate-400 transition-colors hover:border-white/20 hover:text-slate-200 disabled:opacity-40">{e}</button>
        ))}
      </div>
      {!admin.token && <p className="mt-3 text-[12px] text-slate-500">Vul het admin-token in om te vragen. Elke vraag wordt als taak vastgelegd.</p>}
      <div className="mt-5 space-y-5">
        {admin.busy === "/api/copilot/ask" && <Skeleton className="h-24" />}
        {log.map((a, i) => (
          <article key={i} className="fade-up border-t border-white/[.05] pt-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-[14px] font-medium text-white">{a.question}</h3>
              <span className="caption">{a.mode === "claude" ? "geformuleerd door Claude" : "feitelijk antwoord, zonder taalmodel"} · onderwerp {a.topic}</span>
            </div>
            <p className="mt-2 whitespace-pre-line text-[13.5px] leading-relaxed text-slate-200">{a.answer}</p>
            {a.evidence.length > 0 && (
              <details className="mt-3 text-[12.5px]">
                <summary className="cursor-pointer text-slate-400 hover:text-slate-200">Bewijs ({a.evidence.length})</summary>
                <ul className="mt-2 space-y-1.5">
                  {a.evidence.map((f, j) => (
                    <li key={j} className="flex gap-2.5">
                      <code className="shrink-0 font-mono text-[11px] text-cyan-300">{f.ref}</code>
                      {f.href ? <a href={f.href} className="text-slate-300 hover:text-white">{f.text}</a> : <span className="text-slate-300">{f.text}</span>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {a.mode === "claude" && a.data_gaps.length > 0 && <p className="mt-2 text-[12px] text-amber-300/90">Ontbreekt: {a.data_gaps.join(" · ")}</p>}
          </article>
        ))}
      </div>
    </Panel>
  );
}

function Tasks({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const [filter, setFilter] = useState<"open" | "escalated" | "all">("open");
  const { data, loading, refresh } = useApi<Task[]>("/api/central/tasks?limit=120", 30_000);
  const rows = (data ?? []).filter((t) => filter === "all" ? true : filter === "escalated" ? t.status === "escalated"
    : ["queued", "running", "escalated"].includes(t.status));
  const waiting = (data ?? []).filter((t) => t.status === "escalated").length;
  return (
    <Panel title="Takenwachtrij NEXUS Central"
      action={<div className="flex items-center gap-3">
        <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/central/step", undefined, refresh)}>Orkestratiestap</Btn>
        <Segmented label="Filter" value={filter} onChange={setFilter}
          options={[["open", "Open"], ["escalated", `Wacht op CEO · ${waiting}`], ["all", "Alles"]]} />
      </div>}>
      {loading && !data ? <Skeleton className="h-40" /> : rows.length === 0 ? (
        <Empty>{filter === "all" ? "Nog geen taken. Een orkestratiestap maakt taken uit echte gebeurtenissen (nieuws, hypotheses, voorstellen)." : "Niets open."}</Empty>
      ) : (
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full min-w-[760px] text-[13px]">
            <thead><tr className="caption text-left"><th className="px-1 pb-2.5 font-normal">#</th><th className="pb-2.5 font-normal">Taak</th>
              <th className="pb-2.5 font-normal">Rol</th><th className="pb-2.5 font-normal">Status</th><th className="pb-2.5 font-normal">Bijgewerkt</th><th /></tr></thead>
            <tbody>
              {rows.slice(0, 40).map((t) => {
                const [st, c] = STATUS_TEXT[t.status] ?? [t.status, "text-slate-400"];
                return (
                  <tr key={t.id} className="border-t border-white/[.04] align-top">
                    <td className="num px-1 py-2.5 text-slate-500">{t.id}</td>
                    <td className="py-2.5 pr-4"><div className="text-slate-200">{t.reason}</div>
                      <div className="text-[11.5px] text-slate-500">{t.kind}{t.subject ? ` · ${t.subject}` : ""}{t.error ? ` · ${t.error}` : ""}</div></td>
                    <td className="py-2.5 text-slate-400">{t.agent}</td>
                    <td className={`py-2.5 ${c}`}>{st}</td>
                    <td className="py-2.5 text-slate-500">{ago(t.updated_at)}</td>
                    <td className="py-2.5 text-right">
                      {t.status === "escalated" && (
                        <span className="inline-flex gap-1.5">
                          <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post(`/api/central/tasks/${t.id}/decide`, { decision: "acknowledge", note: "gezien door CEO" }, refresh)}>Akkoord</Btn>
                          <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post(`/api/central/tasks/${t.id}/decide`, { decision: "cancel", note: "afgewezen door CEO" }, refresh)}>Afwijzen</Btn>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-[12px] text-slate-500">Akkoord betekent &ldquo;gezien en afgehandeld&rdquo;. Het keurt geen order goed: elke order gaat altijd door de Risk Guardian, en live handelen staat uit.</p>
    </Panel>
  );
}

function HoldoutStatus() {
  const { data } = useApi<Holdout>("/api/holdout/status", 300_000);
  if (!data) return null;
  return (
    <Panel title="Holdout-bewaking" action={<span className={`text-[12px] ${data.contamination.length ? "text-amber-300" : "text-emerald-300"}`}>{data.contamination.length ? "Holdout besmet: wacht op nieuwe data" : "Schoon"}</span>}>
      <div className="grid gap-4 text-[13px] md:grid-cols-3">
        <div><div className="caption">Geregistreerde holdout-evaluaties</div><div className="num mt-1 text-[20px] text-white">{data.evaluations}</div></div>
        <div><div className="caption">Minimale prospectieve periode</div><div className="num mt-1 text-[20px] text-white">{data.min_prospective_days} dagen</div></div>
        <div>
          <div className="caption">Besmette datasets</div>
          {data.contamination.length ? data.contamination.map((c) => (
            <div key={c.datasets} className="mt-1 text-slate-300"><code className="font-mono text-[12px] text-amber-300">{c.datasets}</code> gezien t/m {c.seen_until}; nieuwe meting vanaf {c.prospective_start}
              <div className="text-[12px] text-slate-500">{c.reason}</div></div>
          )) : <div className="mt-1 text-slate-300">geen</div>}
        </div>
      </div>
    </Panel>
  );
}
