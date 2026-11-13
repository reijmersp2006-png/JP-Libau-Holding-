"use client";

import { Btn, useAdmin } from "@/components/admin";
import { DataBadge, Empty, PageTitle, Panel, Skeleton, TruthTag } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, num, pct, tone } from "@/lib/format";

interface Check { key: string; label: string; status: "pass" | "fail" | "unavailable"; value: unknown; threshold: unknown }
interface Tok {
  symbol: string; cashtag: string; chain: string | null; address: string | null;
  price: { last: number; ts: string; ret_1d: number; ret_7d: number; volume_change: number; label: "DELAYED" } | null;
  social: { status: string; at?: string; mentions?: number; unique_authors?: number; mentions_per_hour?: number; bot_risk?: number;
    duplicate_text_share?: number; new_account_share?: number; sentiment_lexicon?: number; top_author_share?: number;
    contract_mentions?: { distinct: number; top: { address: string; mentions: number }[] };
    decay?: { available: boolean; reason?: string; ratio_last_vs_first?: number; state?: string };
    source_meta?: { pages: number; rate_limit: Record<string, string>; fetched_at: string };
    baseline?: { available: boolean; history: number; needed?: number; z?: number | null; unusual?: boolean } };
  safety: { status: string; checks?: Check[]; market?: { liquidity_usd?: number | null; volume_24h_usd?: number | null; dex?: string }; sources?: Record<string, string>; at?: string };
  tradeable: [boolean, string];
}
interface Radar { x: { connected: boolean; detail: string }; tokens: Tok[]; rule: string }

const SAFETY: Record<string, [string, string]> = {
  pass: ["Geslaagd", "text-emerald-300"], fail: ["Gezakt", "text-rose-300"], unavailable: ["Onvolledig", "text-amber-300"],
  not_checked: ["Nog niet gecontroleerd", "text-slate-400"], not_applicable: ["Eigen keten, geen contract", "text-slate-400"],
};
const usd = (v: number | null | undefined) => v == null ? "—" : `$${v >= 1e6 ? `${num(v / 1e6, 1)} mln` : num(v, 0)}`;

export default function Page() {
  const admin = useAdmin();
  const { data, loading, error, refresh } = useApi<Radar>("/api/social/radar", 120_000);
  return (
    <>
      <PageTitle title="Social Radar"
        sub="Meme-coins en sociale dynamiek uit de officiële X API, met verplichte on-chain veiligheidscontroles (GoPlus, DexScreener). Dit zijn onderzoekssignalen, geen handelsadvies: zonder geslaagde controle komt er nooit een voorstel."
        right={<div className="flex items-center gap-3">{admin.field}
          <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/social/refresh", undefined, refresh)}>Nu meten</Btn></div>} />
      {loading && !data ? <Skeleton className="h-96" /> : error && !data ? <Empty>Radar niet te laden: {error}</Empty> : data && (
        <div className="space-y-5">
          <section className="panel fade-up grid gap-6 p-5 md:grid-cols-3">
            <div>
              <div className="caption flex items-center gap-2">X API <TruthTag kind={data.x.connected ? "connected" : "unavailable"} /></div>
              <div className="mt-1.5 text-[14px] text-slate-200">{data.x.detail}</div>
              <div className="mt-1 text-[12px] text-slate-500">Alleen de officiële API; geen scraping.</div>
            </div>
            <div>
              <div className="caption">Uitvoerbaar nu</div>
              <div className="num mt-1.5 text-[22px] font-semibold text-white">{data.tokens.filter((t) => t.tradeable[0]).length} / {data.tokens.length}</div>
              <div className="mt-1 text-[12px] text-slate-500">na veiligheidscontrole; voorstellen gaan daarna nog door de Risk Guardian</div>
            </div>
            <div className="text-[12.5px] leading-relaxed text-slate-400">{data.rule}</div>
          </section>

          <div className="grid gap-5 lg:grid-cols-3">
            {data.tokens.map((t) => <TokenCard key={t.symbol} t={t} />)}
          </div>

          <Panel title="Sociaal vóór de koers?">
            <p className="text-[13px] leading-relaxed text-slate-400">De lead/lag-analyse (kruiscorrelatie van vermeldingen per uur tegen koersrendement, met een 95%-grens) en de
              betrouwbaarheid van accounts hebben minstens 30 gelijktijdige metingen en 10 uitkomsten per account nodig. Zonder X-verbinding zijn er nul metingen, dus
              er is nog <b className="font-medium text-slate-200">geen uitspraak</b>. Dat is de eerlijke stand.</p>
          </Panel>
        </div>
      )}
    </>
  );
}

function TokenCard({ t }: { t: Tok }) {
  const [st, sc] = SAFETY[t.safety.status] ?? [t.safety.status, "text-slate-400"];
  const s = t.social;
  return (
    <section className="panel fade-up flex flex-col p-5">
      <header className="flex items-start justify-between gap-2">
        <div>
          <h2 className="title-md">{t.symbol}</h2>
          <div className="mt-0.5 text-[12px] text-slate-500">${t.cashtag}{t.chain ? ` · chain ${t.chain}` : ""}</div>
        </div>
        <span className={`text-[12px] font-medium ${t.tradeable[0] ? "text-emerald-300" : "text-slate-400"}`} title={t.tradeable[1]}>
          {t.tradeable[0] ? "Uitvoerbaar" : "Alleen onderzoek"}
        </span>
      </header>

      <div className="mt-4 grid grid-cols-3 gap-3 border-b border-white/[.05] pb-4">
        {t.price ? (
          <>
            <div><div className="caption flex items-center gap-1.5">Koers <DataBadge label={t.price.label} /></div><div className="num mt-1 text-[14px] text-white">€{num(t.price.last, t.price.last < 0.01 ? 8 : 4)}</div></div>
            <div><div className="caption">7 dagen</div><div className={`num mt-1 text-[14px] ${tone(t.price.ret_7d)}`}>{pct(t.price.ret_7d, 1, true)}</div></div>
            <div><div className="caption">Volume vs 7d</div><div className={`num mt-1 text-[14px] ${tone(t.price.volume_change)}`}>{pct(t.price.volume_change, 0, true)}</div></div>
          </>
        ) : <div className="col-span-3 text-[12.5px] text-slate-500">Geen koersdata.</div>}
      </div>

      <div className="mt-4">
        <div className="caption mb-1.5">Sociaal</div>
        {s.status === "ok" ? (
          <dl className="num grid grid-cols-2 gap-x-4 gap-y-1 text-[12.5px]">
            <dt className="text-slate-500">vermeldingen / uur</dt><dd className="text-right text-slate-200">{num(s.mentions_per_hour, 1)}</dd>
            <dt className="text-slate-500">unieke auteurs</dt><dd className="text-right text-slate-200">{s.unique_authors}</dd>
            <dt className="text-slate-500">botrisico</dt><dd className={`text-right ${(s.bot_risk ?? 0) > 0.5 ? "text-rose-300" : "text-slate-200"}`}>{pct(s.bot_risk, 0)}</dd>
            <dt className="text-slate-500">grootste account</dt><dd className="text-right text-slate-200">{pct(s.top_author_share, 0)}</dd>
            <dt className="text-slate-500">momentum</dt><dd className="text-right text-slate-200">{s.decay?.available ? `${s.decay.state} (${num(s.decay.ratio_last_vs_first, 1)}×)` : "te weinig posts"}</dd>
            <dt className="text-slate-500">contractadressen</dt><dd className={`text-right ${(s.contract_mentions?.distinct ?? 0) > 1 ? "text-amber-300" : "text-slate-200"}`}>{s.contract_mentions?.distinct ?? 0}{(s.contract_mentions?.distinct ?? 0) > 1 ? " · let op nep-tokens" : ""}</dd>
            <dt className="text-slate-500">t.o.v. normaal</dt><dd className="text-right text-slate-200">{s.baseline?.available ? `${num(s.baseline.z, 1)}σ` : `basislijn ${s.baseline?.history ?? 0}/${s.baseline?.needed ?? 5}`}</dd>
          </dl>
        ) : null}
        {s.status === "ok" && s.source_meta && <div className="mt-1 text-[11px] text-slate-500">gemeten {ago(s.source_meta.fetched_at)} · {s.source_meta.pages} pagina&apos;s{s.source_meta.rate_limit?.["x-rate-limit-remaining"] ? ` · limiet over: ${s.source_meta.rate_limit["x-rate-limit-remaining"]}` : ""}</div>}
        {s.status !== "ok" && <div className="text-[12.5px] text-slate-500">{s.status === "not_connected" ? "X niet verbonden: geen metingen." : "Nog geen meting."}</div>}
      </div>

      <div className="mt-4 flex-1">
        <div className="flex items-baseline justify-between"><span className="caption">Veiligheid</span><span className={`text-[12px] ${sc}`}>{st}</span></div>
        {t.safety.checks?.length ? (
          <ul className="mt-1.5 space-y-1 text-[12.5px]">
            {t.safety.checks.map((c) => (
              <li key={c.key} className="flex justify-between gap-2">
                <span className="text-slate-400">{c.label}</span>
                <span className={c.status === "pass" ? "text-emerald-300" : c.status === "fail" ? "text-rose-300" : "text-amber-300"}>
                  {c.status === "pass" ? "ok" : c.status === "fail" ? "gezakt" : "geen data"}</span>
              </li>
            ))}
          </ul>
        ) : t.address ? <p className="mt-1.5 text-[12.5px] text-slate-500">Geen controle opgeslagen. Ontbrekende data telt als &ldquo;niet geslaagd&rdquo;.</p> : null}
        {t.safety.market && <div className="mt-2 text-[12px] text-slate-500">liquiditeit {usd(t.safety.market.liquidity_usd)} · volume 24u {usd(t.safety.market.volume_24h_usd)}</div>}
      </div>
      <div className="mt-4 text-[11.5px] text-slate-600">{t.tradeable[1]}{t.safety.at ? ` · ${ago(t.safety.at)}` : ""}</div>
    </section>
  );
}
