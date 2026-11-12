"use client";

import { Spark } from "@/components/EquityChart";
import { WithCC } from "@/components/useCC";
import { DataBadge, Empty, PageTitle, Panel } from "@/components/ui";
import { ago, num, pct, tone } from "@/lib/format";

const DESKS: Record<string, string> = { crypto: "Crypto", meme: "Memecoins", stocks: "Aandelen", metals: "Goud & zilver", fx: "Valuta" };

export default function Page() {
  return (
    <WithCC>{(d) => {
      const groups = Object.keys(DESKS).map((k) => [k, d.market.filter((q) => q.desk === k)] as const).filter(([, v]) => v.length);
      return (
        <>
          <PageTitle title="Market Radar" sub="Alle instrumenten van de holding met herkomst en leeftijd van de koers. Uurkoersen zijn DELAYED, nooit LIVE." />
          {groups.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {groups.map(([k, qs]) => (
                <Panel key={k} title={DESKS[k]}>
                  <table className="w-full text-sm">
                    <tbody>
                      {qs.map((q) => (
                        <tr key={q.symbol} className="border-t border-white/[.04] first:border-0">
                          <td className="py-2"><div className="font-medium text-slate-100">{q.name}</div><div className="font-mono text-[11px] text-slate-500">{q.symbol}</div></td>
                          <td className="py-2"><DataBadge label={q.label} /><div className="text-[10.5px] text-slate-600">{ago(q.ts)}</div></td>
                          <td className="num py-2 text-right">{q.price == null ? "—" : `${q.currency} ${num(q.price, q.price < 1 ? 6 : 2)}`}</td>
                          <td className={`num py-2 text-right ${tone(q.change)}`}>{pct(q.change, 2, true)}</td>
                          <td className="py-2 pl-3 text-right"><Spark values={q.line} up={(q.change ?? 0) >= 0} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Panel>
              ))}
            </div>
          ) : <Empty>Geen marktdata beschikbaar.</Empty>}
        </>
      );
    }}</WithCC>
  );
}
