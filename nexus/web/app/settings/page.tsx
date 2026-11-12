"use client";

import { WithCC } from "@/components/useCC";
import { DataBadge, PageTitle, Panel, StatusDot } from "@/components/ui";
import { API_BASE } from "@/lib/api";

export default function Page() {
  return (
    <WithCC>{(d) => (
      <>
        <PageTitle title="Settings & Integrations" sub="Verbindingen, omgeving en beveiliging. Sleutels staan alleen op de server; deze pagina ziet ze nooit." />
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Integraties">
            <ul className="space-y-3">
              {d.connections.map((c) => (
                <li key={c.name} className="flex gap-3">
                  <span className="mt-1.5"><StatusDot status={c.status} /></span>
                  <div><div className="flex items-center gap-2 text-sm font-medium">{c.name}<span className="text-xs text-slate-500">{c.kind}</span><DataBadge label={c.label} /></div>
                    <div className="text-xs text-slate-500">{c.detail}</div></div>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Omgeving">
            <dl className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
              <dt className="text-slate-500">API</dt><dd className="font-mono text-xs">{API_BASE}</dd>
              <dt className="text-slate-500">Omgeving</dt><dd>{d.environment}</dd>
              <dt className="text-slate-500">Modus</dt><dd>{d.controls.mode}</dd>
              <dt className="text-slate-500">Live handelen</dt><dd>uitgeschakeld (bestaat niet in deze versie)</dd>
            </dl>
            <div className="mt-4 rounded-lg border border-white/5 bg-white/[.02] p-3 text-xs leading-relaxed text-slate-400">
              Beveiligingsregels: exchange-sleutels nooit met opnamerecht, geen sleutels of wallet-keys in de repo of de frontend,
              wallet-transacties via signing in een eigen wallet in plaats van opgeslagen private keys, elke besturingsactie in de audit-log.
            </div>
          </Panel>
        </div>
      </>
    )}</WithCC>
  );
}
