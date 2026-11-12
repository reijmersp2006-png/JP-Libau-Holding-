"use client";

import { ErrorBox, PageTitle, Panel, Skeleton, Stat } from "@/components/ui";
import { useApi } from "@/lib/api";
import { eur, num } from "@/lib/format";

interface Admin {
  plans: { key: string; name: string; price_eur: number; trial_days: number; limits: Record<string, number>; active: boolean }[];
  organizations: number; users: number; paid_invoices: number; billing_connected: boolean; mrr_eur: number | null;
  churn: number | null; conversion: number | null; ai_cost_eur: number | null; market_data_cost_eur: number;
  uptime_s: number; requests: number; errors_5xx: number; legal_gate: { item: string; done: boolean }[]; customer_features_enabled: boolean;
}
const LIMIT_NAMES: Record<string, string> = { ai_requests_month: "AI-verzoeken / maand", watchlists: "Watchlists", strategies: "Strategieën", paper_accounts: "Paper-accounts" };

export default function Page() {
  const { data, error, loading, refresh } = useApi<Admin>("/api/admin/overview", 30_000);
  if (loading && !data) return <Skeleton className="h-96" />;
  if (error && !data) return <ErrorBox message={error} onRetry={refresh} />;
  const d = data!;
  const na = "niet beschikbaar";
  return (
    <>
      <PageTitle title="SaaS Administration" sub="Voorbereiding op NEXUS als abonnementsdienst. Klantfuncties staan uit tot de juridische toets klaar is; zonder betaalkoppeling tonen we geen omzetcijfers."
        right={<span className="rounded-full border border-amber-400/40 bg-amber-500/10 px-3 py-1 text-xs text-amber-200">Klantfuncties: UIT</span>} />
      <div className="grid gap-4 md:grid-cols-4">
        <Panel><Stat label="Organisaties" value={d.organizations} sub={`${d.users} gebruikers`} /></Panel>
        <Panel><Stat label="MRR" value={d.mrr_eur == null ? "—" : eur(d.mrr_eur)} sub={d.billing_connected ? "" : `${na}: geen betaalprovider gekoppeld`} /></Panel>
        <Panel><Stat label="Churn / conversie" value="—" sub={`${na}: nog geen klanten`} /></Panel>
        <Panel><Stat label="Uptime API" value={d.uptime_s < 3600 ? `${Math.round(d.uptime_s / 60)} min` : `${num(d.uptime_s / 3600, 1)} uur`} sub={`${d.requests} verzoeken, ${d.errors_5xx} serverfouten`} /></Panel>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {d.plans.map((p) => (
          <Panel key={p.key} glow={p.key === "pro"}>
            <div className="flex items-baseline justify-between"><h3 className="text-lg font-semibold">{p.name}</h3><span className="text-xs text-slate-500">{p.active ? "actief" : "inactief"}</span></div>
            <div className="num mt-1 text-3xl font-semibold">{eur(p.price_eur, 0)}<span className="text-sm font-normal text-slate-500"> / maand</span></div>
            <div className="text-xs text-slate-500">voorgestelde prijs, configureerbaar · {p.trial_days} dagen proef</div>
            <ul className="mt-3 space-y-1 text-sm">{Object.entries(p.limits).map(([k, v]) => <li key={k} className="flex justify-between"><span className="text-slate-400">{LIMIT_NAMES[k] ?? k}</span><span className="num">{num(v, 0)}</span></li>)}</ul>
          </Panel>
        ))}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Juridische poort vóór klantfuncties">
          <ul className="space-y-2 text-sm">{d.legal_gate.map((g) => <li key={g.item} className="flex gap-2"><span className={g.done ? "text-emerald-400" : "text-rose-400"}>{g.done ? "✓" : "✗"}</span>{g.item}</li>)}</ul>
          <p className="mt-3 text-xs text-slate-500">Beleggingsadvies, orderuitvoering of vermogensbeheer voor klanten blijft uit tot dit allemaal is afgevinkt. ‘AI-onderzoek’ noemen haalt de regels niet weg.</p>
        </Panel>
        <Panel title="Kosten">
          <dl className="grid grid-cols-[1fr_auto] gap-y-2 text-sm">
            <dt className="text-slate-400">AI-infrastructuur</dt><dd>{d.ai_cost_eur == null ? `— (${na}: nog geen AI-agents)` : eur(d.ai_cost_eur)}</dd>
            <dt className="text-slate-400">Marktdata</dt><dd>{eur(d.market_data_cost_eur)} (alleen gratis bronnen)</dd>
            <dt className="text-slate-400">Betaalde facturen</dt><dd>{d.paid_invoices}</dd>
          </dl>
          <p className="mt-3 text-xs text-slate-500">Volgende stap: Stripe koppelen (abonnementen, proefperiodes, facturen, gebruiksmeting van AI-verzoeken) na de juridische toets.</p>
        </Panel>
      </div>
    </>
  );
}
