"use client";

import { useState } from "react";
import { KillSwitch } from "@/components/KillSwitch";
import { DataBadge, ErrorBox, Meter, PageTitle, Panel, Skeleton } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, eur, num, pct, time } from "@/lib/format";
import type { Controls, Limit, RiskRow } from "@/lib/types";

interface RiskResp { limits: Limit[]; utilization: RiskRow[]; controls: Controls; holding_limits: Record<string, number | Record<string, number>> }
interface Audit { id: number; ts: string; actor: string; action: string; detail: Record<string, unknown> }

const fmtLimit = (l: Limit) => l.key.endsWith("_eur") ? eur(l.value, 0) : l.key === "max_open_positions" ? num(l.value, 0) : pct(l.value, l.value < 0.01 ? 2 : 1);

export default function Page() {
  const risk = useApi<RiskResp>("/api/risk", 15_000);
  const audit = useApi<Audit[]>("/api/audit?limit=30", 15_000);
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  async function release() {
    setMsg(null);
    try {
      await api("/api/controls/kill/release", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ reason: "opgeheven via Risk Guardian" }) });
      setMsg("Noodstop opgeheven."); window.dispatchEvent(new Event("nexus:controls")); risk.refresh(); audit.refresh();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }

  if (risk.loading && !risk.data) return <Skeleton className="h-96" />;
  if (risk.error && !risk.data) return <ErrorBox message={risk.error} onRetry={risk.refresh} />;
  const r = risk.data!;
  return (
    <>
      <PageTitle title="Risk Guardian" sub="Onafhankelijk vetorecht over elk voorstel. Grenzen zijn conservatief, altijd zichtbaar en kunnen alleen strenger. ‘Geen trade’ is altijd een geldig antwoord." />
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Noodstop" glow>
          <KillSwitch status={r.controls.kill} onChange={() => { risk.refresh(); audit.refresh(); }} />
          {r.controls.kill.engaged && (
            <div className="mt-3 space-y-2">
              <label className="block text-xs text-slate-400" htmlFor="tok">Admin-token om op te heffen</label>
              <input id="tok" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off"
                className="w-full rounded-lg border border-slate-700 bg-black/40 px-3 py-2 font-mono text-sm outline-none focus:border-cyan-400/60" />
              <button onClick={release} disabled={!token} className="w-full rounded-lg border border-slate-600 px-3 py-2 text-sm hover:border-cyan-400/60 disabled:opacity-50">Noodstop opheffen</button>
            </div>
          )}
          {msg && <p className="mt-2 text-xs text-slate-300">{msg}</p>}
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">De noodstop zet ook het KILL-bestand van de holding in de gekoppelde map. De paper-bot in de cloud stop je met /noodstop in Jarvis.</p>
        </Panel>
        <Panel title="Live-poort">
          <ul className="space-y-2 text-sm">
            {r.controls.live_gate.map((g) => (
              <li key={g.check} className="flex gap-2"><span className={g.passed ? "text-emerald-400" : "text-rose-400"}>{g.passed ? "✓" : "✗"}</span>
                <div><div className="font-mono text-xs text-slate-300">{g.check}</div><div className="text-xs text-slate-500">{g.detail}</div></div></li>
            ))}
          </ul>
          <p className="mt-3 rounded-md border border-slate-700 px-2 py-1.5 text-center font-mono text-xs text-slate-300">LIVE HANDELEN: UITGESCHAKELD</p>
        </Panel>
        <Panel title="Gebruik nu" label="SIMULATED">
          {r.utilization.length ? (
            <ul className="space-y-3">{r.utilization.map((u) => (
              <li key={u.key}><div className="mb-1 flex justify-between text-xs"><span>{u.label}</span>
                <span className="num text-slate-500">{u.key === "positions" ? `${num(u.used, 0)} / ${num(u.limit, 0)}` : `${pct(u.used, 1)} / ${pct(u.limit, 0)}`}</span></div>
                <Meter value={u.utilization} /></li>))}</ul>
          ) : <p className="text-sm text-slate-500">Geen portefeuille gekoppeld.</p>}
        </Panel>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title="Grenzen van de Risk Guardian (voorstellen)">
          <table className="w-full text-sm"><tbody>
            {r.limits.map((l) => <tr key={l.key} className="border-t border-white/[.04] first:border-0"><td className="py-1.5 text-slate-300">{l.label}</td><td className="num py-1.5 text-right text-cyan-200">{fmtLimit(l)}</td></tr>)}
          </tbody></table>
          <p className="mt-2 text-[11px] text-slate-500">Strenger maken: omgevingsvariabele NEXUS_RISK_&lt;NAAM&gt;. Ruimer wordt geweigerd.</p>
        </Panel>
        <Panel title="Audit-log" label={audit.data?.length ? undefined : undefined}>
          {audit.data?.length ? (
            <ul className="max-h-80 space-y-2 overflow-y-auto text-sm">
              {audit.data.map((a) => (
                <li key={a.id} className="flex justify-between gap-3 border-t border-white/[.04] pt-2 first:border-0 first:pt-0">
                  <div><span className="font-mono text-xs text-cyan-200">{a.action}</span> <span className="text-xs text-slate-500">door {a.actor}</span>
                    <div className="truncate text-[11px] text-slate-500" title={JSON.stringify(a.detail)}>{JSON.stringify(a.detail)}</div></div>
                  <span className="shrink-0 text-[11px] text-slate-500" title={time(a.ts)}>{ago(a.ts)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-500">Nog geen acties gelogd.</p>}
        </Panel>
      </div>
      <p className="mt-3 text-[11px] text-slate-600"><DataBadge label="SIMULATED" /> gebruik is gemeten op de paper-portefeuille van de holding.</p>
    </>
  );
}
