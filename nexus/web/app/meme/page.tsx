"use client";

import { WithCC } from "@/components/useCC";
import { Empty, PageTitle, Panel } from "@/components/ui";
import { pct, tone, usd } from "@/lib/format";

export default function Page() {
  return (
    <WithCC>{(d) => (
      <>
        <PageTitle title="Meme Coin Scanner"
          sub="Hoog-risico radar via DexScreener: alleen kijken. Gehandeld wordt uitsluitend op gereguleerde exchanges, en alleen met contract-, honeypot- en liquiditeitschecks (die nog gebouwd worden). Hype alleen is nooit een reden." />
        <div className="mb-4 grid gap-3 md:grid-cols-3">
          {[["Contract- & honeypotcheck", "fase 2 · nog niet"], ["Houderverdeling & dev-wallets", "fase 2 · nog niet"], ["Liquiditeit & rode vlaggen", "draait (DexScreener)"]].map(([t, s]) => (
            <Panel key={t}><div className="text-sm font-medium text-slate-200">{t}</div><div className="text-xs text-slate-500">{s}</div></Panel>
          ))}
        </div>
        <Panel title="Radar (laatste ophaalronde)" label={d.environment === "demo" ? "SIMULATED" : d.radar.length ? "DELAYED" : "UNAVAILABLE"}>
          {d.radar.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                  <th className="pb-2">Token</th><th className="pb-2">Chain</th><th className="pb-2 text-right">Prijs</th>
                  <th className="pb-2 text-right">Liquiditeit</th><th className="pb-2 text-right">Volume 24u</th><th className="pb-2 text-right">24u</th><th className="pb-2 pl-3">Rode vlaggen</th></tr></thead>
                <tbody>
                  {d.radar.map((r, i) => (
                    <tr key={i} className="border-t border-white/[.04]">
                      <td className="py-2 font-medium text-slate-100">{r.symbol}</td>
                      <td className="py-2 text-slate-400">{r.chain}</td>
                      <td className="num py-2 text-right">{usd(r.price_usd)}</td>
                      <td className={`num py-2 text-right ${r.liquidity_usd < 250_000 ? "text-rose-300" : ""}`}>{usd(r.liquidity_usd)}</td>
                      <td className="num py-2 text-right">{usd(r.volume_24h_usd)}</td>
                      <td className={`num py-2 text-right ${tone(r.change_24h_pct)}`}>{pct(r.change_24h_pct / 100, 1, true)}</td>
                      <td className="py-2 pl-3">{r.flags.length ? r.flags.map((f) => <span key={f} className="mr-1 rounded bg-rose-500/15 px-1.5 py-0.5 text-[11px] text-rose-300">{f}</span>) : <span className="text-xs text-slate-600">geen</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty>Geen radardata.</Empty>}
        </Panel>
      </>
    )}</WithCC>
  );
}
