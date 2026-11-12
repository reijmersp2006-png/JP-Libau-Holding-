"use client";

import { WithCC } from "@/components/useCC";
import { Panel, PageTitle } from "@/components/ui";
import { ago } from "@/lib/format";

const STATUS = {
  operational: { t: "Draait", c: "text-emerald-300 border-emerald-400/30 bg-emerald-400/10" },
  partial: { t: "Deels", c: "text-amber-300 border-amber-400/30 bg-amber-400/10" },
  not_built: { t: "Nog niet gebouwd", c: "text-slate-400 border-slate-600 bg-slate-500/5" },
};

export default function Page() {
  return (
    <WithCC>{(d) => (
      <>
        <PageTitle title="AI Expert Council"
          sub="Dertien rollen, met eerlijk per rol wat er al echt draait en waarop. Er wordt geen agent-activiteit verzonnen: ‘laatst actief’ komt uit echte tijdstempels. De echte Council-runs (Claude, debat, trackrecord en kalibratie) staan in het Evolution Lab onder Agent Council." />
        <Panel title="Besluitvorming" className="mb-4">
          <ol className="flex flex-wrap items-center gap-1.5 text-xs">
            {["Data ophalen", "Datakwaliteit", "Marktregime", "Kansen", "Agent-analyse", "Strategie-toets", "Portefeuille-impact", "Risk Guardian (veto)", "Uitvoeringsplan", "Paper / live", "Monitoring"].map((s, i) => {
              const live = [0, 1, 2, 3, 5, 6, 7, 9, 10].includes(i);
              return (
                <li key={s} className="flex items-center gap-1.5">
                  <span className={`rounded-md border px-2 py-1 ${live ? "border-cyan-400/30 text-cyan-200" : "border-slate-700 text-slate-500"}`}>{s}</span>
                  {i < 10 && <span className="text-slate-700">→</span>}
                </li>
              );
            })}
          </ol>
          <p className="mt-2 text-[11px] text-slate-500">Cyaan: draait al in de paper-bot (zonder LLM). Grijs: komt in fase 3 tot 6. Live staat altijd uit.</p>
        </Panel>
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
          {d.agents.items.map((a) => (
            <Panel key={a.id}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-mono text-[10px] text-slate-600">AGENT {String(a.n).padStart(2, "0")}</div>
                  <h3 className="font-semibold text-slate-100">{a.name}</h3>
                </div>
                <span className={`rounded-md border px-2 py-0.5 text-[11px] ${STATUS[a.status].c}`}>{STATUS[a.status].t}</span>
              </div>
              {a.backed_by && <div className="mt-1 font-mono text-[11px] text-cyan-300/70">{a.backed_by}</div>}
              {a.covers.length > 0 && <ul className="mt-2 space-y-0.5 text-xs text-slate-300">{a.covers.map((c) => <li key={c}>✓ {c}</li>)}</ul>}
              {a.missing.length > 0 && <ul className="mt-1.5 space-y-0.5 text-xs text-slate-500">{a.missing.map((c) => <li key={c}>○ {c}</li>)}</ul>}
              <div className="mt-2 flex justify-between border-t border-white/5 pt-2 text-[11px] text-slate-500">
                <span>Fase {a.phase}</span><span>{a.status === "not_built" ? "geen activiteit" : `laatst actief: ${a.last_activity ? ago(a.last_activity) : "onbekend"}`}</span>
              </div>
            </Panel>
          ))}
        </div>
      </>
    )}</WithCC>
  );
}
