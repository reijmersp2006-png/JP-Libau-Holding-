"use client";

import { useState } from "react";
import { EquityChart } from "@/components/EquityChart";
import { DataBadge, Empty, ErrorBox, PageTitle, Panel, Skeleton, Stat } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, eur, num, pct, tone } from "@/lib/format";
import type { PaperOverview, Proposal } from "@/lib/types";

const STATUS: Record<string, string> = { new: "text-cyan-300", partially_filled: "text-amber-300", filled: "text-emerald-300", cancelled: "text-slate-400", rejected: "text-rose-300" };

function NewProposal({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ symbol: "BTC-EUR", asset_class: "crypto", entry_price: "", stop_loss: "", size_eur: "50", liquidity: "50000000",
    evidence: "", counter: "", avoid: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  async function submit() {
    setMsg(null);
    const entry = Number(f.entry_price), stop = Number(f.stop_loss), size = Number(f.size_eur);
    try {
      const r = await api<{ approved: boolean; reason: string }>("/api/proposals", { method: "POST", body: JSON.stringify({
        idempotency_key: `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, source: "manual", symbol: f.symbol,
        asset_class: f.asset_class, direction: "buy", strategy_id: "handmatig", entry_conditions: "handmatig voorstel",
        entry_price: entry, size_eur: size, stop_loss: stop, take_profit: "handmatig beoordelen", holding_period: "onbepaald",
        est_fee_pct: 0.0025, est_slippage_pct: 0.001, spread_pct: 0.001, available_liquidity_eur: Number(f.liquidity),
        evidence: [f.evidence], counterarguments: [f.counter], reasons_to_avoid: [f.avoid],
        max_modeled_loss_eur: size * Math.max(0, (entry - stop) / entry), scenario_risks: ["koers springt over de stop heen"],
        input_data_label: "DELAYED" }) });
      setMsg(r.approved ? "Goedgekeurd door de Risk Guardian. Voer hem hieronder uit." : `Veto: ${r.reason}`);
      onDone();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }
  const input = "w-full rounded-lg border border-slate-700 bg-black/40 px-2.5 py-1.5 text-sm";
  return (
    <Panel title="Nieuw paper-voorstel (handmatig)">
      <div className="grid grid-cols-2 gap-2 text-xs">
        <label>Instrument<input className={input} value={f.symbol} onChange={set("symbol")} /></label>
        <label>Klasse<select className={input} value={f.asset_class} onChange={set("asset_class")}>{["crypto", "meme", "stocks", "metals", "fx"].map((c) => <option key={c}>{c}</option>)}</select></label>
        <label>Instapkoers (€)<input className={input} value={f.entry_price} onChange={set("entry_price")} inputMode="decimal" /></label>
        <label>Stop-loss (€)<input className={input} value={f.stop_loss} onChange={set("stop_loss")} inputMode="decimal" /></label>
        <label>Bedrag (€)<input className={input} value={f.size_eur} onChange={set("size_eur")} inputMode="decimal" /></label>
        <label>Liquiditeit 24u (€)<input className={input} value={f.liquidity} onChange={set("liquidity")} inputMode="decimal" /></label>
        <label className="col-span-2">Bewijs<input className={input} value={f.evidence} onChange={set("evidence")} /></label>
        <label className="col-span-2">Tegenargument<input className={input} value={f.counter} onChange={set("counter")} /></label>
        <label className="col-span-2">Reden om het niet te doen<input className={input} value={f.avoid} onChange={set("avoid")} /></label>
      </div>
      <button onClick={submit} disabled={!f.entry_price || !f.stop_loss || !f.evidence || !f.counter || !f.avoid}
        className="mt-3 w-full rounded-lg border border-cyan-400/50 px-3 py-2 text-sm text-cyan-200 hover:bg-cyan-400/10 disabled:opacity-40">Laat de Risk Guardian beoordelen</button>
      {msg && <p className="mt-2 text-xs text-slate-300">{msg}</p>}
    </Panel>
  );
}

export default function Page() {
  const paper = useApi<PaperOverview>("/api/paper", 15_000);
  const props = useApi<Proposal[]>("/api/proposals?limit=20", 15_000);
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = () => { paper.refresh(); props.refresh(); };

  async function act(path: string) {
    setMsg(null);
    try { await api(path, { method: "POST" }); refresh(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }
  if (paper.loading && !paper.data) return <Skeleton className="h-96" />;
  if (paper.error && !paper.data) return <ErrorBox message={paper.error} onRetry={refresh} />;
  const d = paper.data!, a = d.account;
  const ready = (props.data ?? []).filter((p) => p.status === "approved_by_guardian");
  return (
    <>
      <PageTitle title="Execution Monitor" sub="Het NEXUS paper-account: gesimuleerde orders tegen echte (vertraagde) koersen, met kosten, spread, slippage en gedeeltelijke vullingen. Er is geen verbinding met een broker; live handelen staat uit."
        right={<span className="rounded-full border border-violet-400/40 bg-violet-500/10 px-3 py-1 text-xs text-violet-200">PAPER · geen echt geld</span>} />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Panel title="Paper-account" label={a.label} glow>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Vermogen" value={eur(a.equity_eur)} sub={`start ${eur(a.starting_cash, 0)}`} />
            <Stat label="Resultaat" value={eur(a.pnl_eur)} valueClass={tone(a.pnl_eur)} sub={`gereal. ${eur(a.realized_eur)}`} />
            <Stat label="Kas" value={eur(a.cash_eur)} sub={`posities ${eur(a.positions_value_eur)}`} />
            <Stat label="Kosten" value={eur(a.fees_eur)} sub={`drawdown ${pct(-a.drawdown, 1)}`} />
          </div>
          <div className="mt-4"><EquityChart curve={a.equity_curve} capital={a.starting_cash} height={200} /></div>
        </Panel>
        <div className="space-y-4">
          <Panel title="Reconciliatie">
            <div className={`flex items-center gap-2 text-sm ${d.reconciliation.ok ? "text-emerald-300" : "text-rose-300"}`}>
              <span className={`h-2 w-2 rounded-full ${d.reconciliation.ok ? "bg-emerald-400" : "bg-rose-500"}`} />
              {d.reconciliation.ok ? "Alle vullingen sluiten op kas en posities" : "Verschil gevonden"}</div>
            {d.reconciliation.differences.map((x) => <p key={x} className="mt-1 text-xs text-rose-300">{x}</p>)}
            <p className="mt-1 text-[11px] text-slate-500">gecontroleerd {ago(d.reconciliation.checked_at)} · max. {pct(d.settings.participation, 0)} van de uuromzet per ronde · spread {pct(d.settings.spread_pct, 2)}</p>
            <button onClick={() => act("/api/paper/step")} className="mt-3 w-full rounded-lg border border-slate-600 px-3 py-1.5 text-sm hover:border-cyan-400/60">Simulatieronde nu draaien</button>
          </Panel>
          <Panel title={`Klaar om uit te voeren (${ready.length})`}>
            {ready.length ? (
              <ul className="space-y-2 text-sm">{ready.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2">
                  <span><b>{p.symbol}</b> <span className="text-slate-500">{p.direction} · {eur(Number(p.proposal.size_eur))}</span></span>
                  <button onClick={() => act(`/api/proposals/${p.id}/execute`)} className="rounded-md bg-cyan-400 px-2.5 py-1 text-xs font-semibold text-void hover:bg-cyan-300">Paper-order</button>
                </li>))}</ul>
            ) : <Empty>Geen goedgekeurde voorstellen.</Empty>}
            {msg && <p className="mt-2 text-xs text-rose-300">{msg}</p>}
          </Panel>
        </div>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Panel title={`Orders (${d.orders.length})`}>
            {d.orders.length ? (
              <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-sm [&_td]:px-2 [&_th]:px-2">
                <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500"><th className="pb-2">#</th><th className="pb-2">Instrument</th><th className="pb-2">Kant</th><th className="pb-2 text-right">Gevraagd</th><th className="pb-2 text-right">Gevuld</th><th className="pb-2">Status</th><th className="pb-2">Bijgewerkt</th><th /></tr></thead>
                <tbody>{d.orders.map((o) => (
                  <tr key={o.id} className="border-t border-white/[.04]"><td className="py-2 text-slate-500">{o.id}</td><td className="py-2">{o.symbol}</td><td className="py-2">{o.side}</td>
                    <td className="num py-2 text-right">{o.side === "buy" ? eur(o.notional_eur) : num(o.quantity, 6)}</td>
                    <td className="num py-2 text-right">{o.side === "buy" ? eur(o.filled_notional_eur) : num(o.filled_quantity, 6)}</td>
                    <td className={`py-2 ${STATUS[o.status]}`}>{o.status}{o.reject_reason ? ` (${o.reject_reason})` : ""}</td>
                    <td className="py-2 text-slate-500">{ago(o.updated_at)}</td>
                    <td className="py-2 text-right">{["new", "partially_filled"].includes(o.status) && <button onClick={() => act(`/api/paper/orders/${o.id}/cancel`)} className="text-xs text-slate-400 hover:text-rose-300">annuleer</button>}</td></tr>))}</tbody>
              </table></div>
            ) : <Empty>Nog geen orders. Een order ontstaat alleen uit een voorstel dat de Risk Guardian goedkeurde.</Empty>}
          </Panel>
          <Panel title={`Vullingen (${d.executions.length})`}>
            {d.executions.length ? (
              <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-sm [&_td]:px-2 [&_th]:px-2">
                <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500"><th className="pb-2">Tijd</th><th className="pb-2">Instrument</th><th className="pb-2">Kant</th><th className="pb-2 text-right">Aantal</th><th className="pb-2 text-right">Prijs</th><th className="pb-2 text-right">Slippage</th><th className="pb-2 text-right">Kosten</th><th className="pb-2">Koers</th></tr></thead>
                <tbody>{d.executions.map((e) => (
                  <tr key={e.id} className="border-t border-white/[.04]"><td className="py-2 text-slate-400">{ago(e.ts)}</td><td className="py-2">{e.symbol}</td><td className="py-2">{e.side}</td>
                    <td className="num py-2 text-right">{num(e.quantity, 6)}</td><td className="num py-2 text-right">{eur(e.price_eur, e.price_eur < 1 ? 6 : 2)}</td>
                    <td className="num py-2 text-right">{num(e.slippage_bps, 1)} bp</td><td className="num py-2 text-right">{eur(e.fee_eur)}</td><td className="py-2"><DataBadge label={e.data_label} /></td></tr>))}</tbody>
              </table></div>
            ) : <Empty>Nog geen vullingen.</Empty>}
          </Panel>
          <Panel title="Posities" label={a.label}>
            {a.positions.length ? (
              <table className="w-full text-sm"><tbody>{a.positions.map((p) => (
                <tr key={p.symbol} className="border-t border-white/[.04] first:border-0"><td className="py-2 font-medium">{p.symbol}</td><td className="num py-2 text-right text-slate-400">{num(p.quantity, 6)}</td>
                  <td className="num py-2 text-right"><DataBadge label={p.price_label} className="mr-1.5" />{eur(p.price_eur)}</td><td className="num py-2 text-right">{eur(p.value_eur)}</td>
                  <td className={`num py-2 text-right ${tone(p.unrealized_eur)}`}>{eur(p.unrealized_eur)}</td></tr>))}</tbody></table>
            ) : <Empty>Geen posities.</Empty>}
          </Panel>
        </div>
        <NewProposal onDone={refresh} />
      </div>
    </>
  );
}
