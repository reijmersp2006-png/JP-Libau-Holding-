"use client";

import { WithCC } from "@/components/useCC";
import { Empty, PageTitle, Panel } from "@/components/ui";
import { time } from "@/lib/format";

export default function Page() {
  return (
    <WithCC>{(d) => {
      const items = [...d.decisions, ...d.findings].sort((a, b) => b.ts.localeCompare(a.ts));
      return (
        <>
          <PageTitle title="Trade Journal" sub="Elke beslissing van de paper-bot met reden en het oordeel van de risico-afdeling, plus wat de verkenners zagen. Rechtstreeks uit het logboek van de holding." />
          <Panel label={d.portfolio?.label ?? "UNAVAILABLE"} title="Logboek">
            {items.length ? (
              <ol className="relative space-y-4 border-l border-white/10 pl-5">
                {items.map((f, i) => (
                  <li key={i}>
                    <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${f.kind === "trade" ? "bg-emerald-400" : f.kind === "refused" ? "bg-rose-500" : "bg-amber-400"}`} />
                    <div className="text-[11px] text-slate-500">{time(f.ts)} · {f.desk}{f.strategy ? ` · ${f.strategy}` : ""}</div>
                    <div className="text-sm text-slate-100">{f.text}</div>
                    {f.detail && <div className="mt-0.5 text-xs text-slate-400">{f.detail}</div>}
                  </li>
                ))}
              </ol>
            ) : <Empty>Nog geen beslissingen.</Empty>}
          </Panel>
        </>
      );
    }}</WithCC>
  );
}
