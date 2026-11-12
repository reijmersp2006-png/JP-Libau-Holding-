"use client";

import { WithCC } from "@/components/useCC";
import { DataBadge, Empty, PageTitle, Panel, Stat } from "@/components/ui";
import { eur, pct, tone } from "@/lib/format";

export default function Page() {
  return (
    <WithCC>{(d) => {
      const p = d.portfolio;
      if (!p) return <Empty>Geen portefeuilledata.</Empty>;
      const desks = d.allocation.filter((a) => a.key !== "cash");
      const recon = p.realized_eur + p.unrealized_eur - p.buy_fees_eur;
      const posSum = d.positions.reduce((s, x) => s + x.value_eur, 0);
      return (
        <>
          <PageTitle title="Portfolio Intelligence" sub="Blootstelling per afdeling en per positie, met een controle dat alle cijfers sluiten." />
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Reconciliatie" label={p.label}>
              <div className="grid grid-cols-2 gap-4">
                <Stat label="Cash + posities" value={eur(p.cash_eur + posSum)} sub={`${eur(p.cash_eur)} + ${eur(posSum)}`} />
                <Stat label="Vermogen" value={eur(p.equity_eur)} sub={Math.abs(p.cash_eur + posSum - p.equity_eur) < 0.01 ? "✓ sluit" : "✗ verschil!"} />
                <Stat label="Gereal. + ongereal. − aankoopkosten" value={eur(recon)} />
                <Stat label="Totaal resultaat" value={eur(p.pnl_eur)} valueClass={tone(p.pnl_eur)} sub={Math.abs(recon - p.pnl_eur) < 0.01 ? "✓ sluit" : "✗ verschil!"} />
              </div>
            </Panel>
            <Panel title="Per afdeling" label={p.label}>
              {desks.length ? (
                <ul className="space-y-2 text-sm">
                  {desks.map((a) => {
                    const pos = d.positions.filter((x) => x.desk === a.key);
                    const un = pos.reduce((s, x) => s + (x.unrealized_eur ?? 0), 0);
                    return (
                      <li key={a.key} className="flex items-center justify-between">
                        <span>{a.name} <span className="text-xs text-slate-500">({pos.length} posities)</span></span>
                        <span className="num">{eur(a.value_eur)} <span className="text-slate-500">{pct(a.pct, 1)}</span> <span className={`ml-2 ${tone(un)}`}>{eur(un)}</span></span>
                      </li>
                    );
                  })}
                </ul>
              ) : <Empty>Geen posities.</Empty>}
            </Panel>
          </div>
          <Panel title="Posities" className="mt-4">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                  <th className="pb-2">Instrument</th><th className="pb-2">Afdeling</th><th className="pb-2 text-right">Aantal</th><th className="pb-2 text-right">Gem. prijs</th>
                  <th className="pb-2 text-right">Koers</th><th className="pb-2 text-right">Waarde</th><th className="pb-2 text-right">Gewicht</th><th className="pb-2 text-right">Ongereal.</th></tr></thead>
                <tbody>
                  {d.positions.map((x) => (
                    <tr key={x.desk + x.symbol} className="border-t border-white/[.04]">
                      <td className="py-2 font-medium">{x.symbol}</td><td className="py-2 text-slate-400">{x.desk}</td>
                      <td className="num py-2 text-right text-slate-400">{x.quantity.toPrecision(5)}</td>
                      <td className="num py-2 text-right text-slate-400">{eur(x.avg_eur, x.avg_eur < 1 ? 6 : 2)}</td>
                      <td className="num py-2 text-right"><DataBadge label={x.price_label} className="mr-1.5" />{eur(x.price_eur, x.price_eur != null && x.price_eur < 1 ? 6 : 2)}</td>
                      <td className="num py-2 text-right">{eur(x.value_eur)}</td>
                      <td className="num py-2 text-right text-slate-400">{pct(x.value_eur / p.equity_eur, 1)}</td>
                      <td className={`num py-2 text-right ${tone(x.unrealized_eur)}`}>{eur(x.unrealized_eur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      );
    }}</WithCC>
  );
}
