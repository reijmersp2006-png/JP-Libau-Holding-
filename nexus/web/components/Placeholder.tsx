import Link from "next/link";
import { PageTitle, Panel } from "./ui";

export interface ModuleSpec { title: string; phase: number; purpose: string; existing: string[]; next: string[]; sources?: string[] }

/** Eerlijke pagina voor een module die nog niet gebouwd is: geen nepgrafieken, wel wat er al
 *  is (in de holding) en wat er precies komt. */
export function Placeholder({ spec }: { spec: ModuleSpec }) {
  return (
    <div>
      <PageTitle title={spec.title} sub={spec.purpose}
        right={<span className="rounded-full border border-slate-600 px-3 py-1 font-mono text-xs text-slate-400">Fase {spec.phase} · nog niet gebouwd</span>} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Wat er al bestaat">
          {spec.existing.length ? (
            <ul className="space-y-2 text-sm text-slate-300">{spec.existing.map((e) => <li key={e} className="flex gap-2"><span className="text-emerald-400">✓</span>{e}</li>)}</ul>
          ) : <p className="text-sm text-slate-500">Nog niets.</p>}
        </Panel>
        <Panel title={`Wat er in fase ${spec.phase} komt`}>
          <ul className="space-y-2 text-sm text-slate-300">{spec.next.map((e) => <li key={e} className="flex gap-2"><span className="text-slate-600">○</span>{e}</li>)}</ul>
        </Panel>
        {spec.sources && (
          <Panel title="Benodigde databronnen" className="lg:col-span-2">
            <ul className="space-y-1.5 text-sm text-slate-400">{spec.sources.map((e) => <li key={e}>· {e}</li>)}</ul>
          </Panel>
        )}
      </div>
      <p className="mt-4 text-xs text-slate-600">Er worden hier bewust geen voorbeeldgrafieken getoond: zonder echte data laten we niets zien. <Link href="/" className="text-cyan-300/70 hover:text-cyan-200">Terug naar Command Center</Link></p>
    </div>
  );
}
