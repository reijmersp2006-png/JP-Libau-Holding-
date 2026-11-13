"use client";

import { useState } from "react";
import { Btn, useAdmin } from "@/components/admin";
import { Empty, PageTitle, Panel, Segmented, Skeleton, StatusDot, TruthTag } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, num, pct } from "@/lib/format";

interface Item {
  id: number; source: string; source_kind: string; title: string; url: string; published_at: string; category: string;
  assets: string[] | null; factuality: string | null; expectation: { available: boolean; reason?: string } | null; analysis: Record<string, unknown> | null;
  facts: string[]; relevance: number | null; cluster_key: string | null; duplicate_of: number | null;
  fetched_at: string; analyzed_at: string | null; signal_at: string | null;
}
interface Lat { n: number; median_s: number | null; p90_s: number | null }
interface Reactor {
  items: Item[]; latency: { publication_to_ingest: Lat; ingest_to_analysis: Lat; analysis_to_signal: Lat; note: string };
  feeds: { key: string; name: string; kind: string; status: { status?: string; new?: number; error?: string } | string | null }[];
  last_fetch: string | null; signal_threshold: number;
  event_study: { category: string; symbol: string; events: number; mean_z: number; share_up: number; mean_z_ci95?: [number, number]; conclusion: string }[];
}

const STEPS = ["Bron + publicatietijd", "Binnenkomsttijd", "Instrumenten", "Ontdubbelen", "Feiten", "Feit of speculatie",
  "Verwachting", "Relevantie", "Koersreactie", "Gestructureerd event", "Naar Council", "Opslaan"];

function dur(s: number | null) {
  if (s == null) return "—";
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 120) return `${num(s, 1)} s`;
  if (s < 7200) return `${num(s / 60, 0)} min`;
  return `${num(s / 3600, 1)} uur`;
}

export default function Page() {
  const admin = useAdmin();
  const { data, loading, error, refresh } = useApi<Reactor>("/api/news/reactor?limit=120", 60_000);
  const [view, setView] = useState<"signals" | "all" | "dupes">("signals");

  const items = data?.items ?? [];
  const rows = items.filter((i) => view === "all" ? true : view === "dupes" ? i.duplicate_of != null
    : i.duplicate_of == null && (i.relevance ?? 0) >= (data?.signal_threshold ?? 0.6));
  const okFeeds = (data?.feeds ?? []).filter((f) => typeof f.status === "object" && f.status?.status === "ok").length;

  return (
    <>
      <PageTitle title="News Reactor"
        sub="Officiële bronnen met toegestane feeds, verwerkt in twaalf vaste stappen. Elke stap heeft een echte tijdstempel; nieuws leidt nooit direct tot een order, alleen tot een gestructureerd event voor de Council en de Risk Guardian."
        right={<div className="flex items-center gap-3">{admin.field}
          <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/news/ingest", undefined, refresh)}>Nu ophalen</Btn></div>} />

      {loading && !data ? <Skeleton className="h-96" /> : error && !data ? <Empty>News Reactor niet te laden: {error}</Empty> : data && (
        <div className="space-y-5">
          <section className="panel fade-up grid gap-6 p-5 md:grid-cols-4" aria-label="Status en vertraging">
            <div>
              <div className="caption flex items-center gap-2">Bronnen <TruthTag kind={data.last_fetch ? (okFeeds ? "connected" : "unavailable") : "unavailable"} /></div>
              <div className="num mt-1.5 text-[22px] font-semibold text-white">{okFeeds} / {data.feeds.length}</div>
              <div className="mt-1 text-[12px] text-slate-500">{data.last_fetch ? `laatste ophaalronde ${ago(data.last_fetch)}` : "nog nooit opgehaald"}</div>
            </div>
            {([["Publicatie → binnen", data.latency.publication_to_ingest], ["Binnen → analyse", data.latency.ingest_to_analysis],
              ["Analyse → signaal", data.latency.analysis_to_signal]] as const).map(([k, l]) => (
              <div key={k}>
                <div className="caption">{k} · mediaan</div>
                <div className="num mt-1.5 text-[22px] font-semibold text-white">{dur(l.median_s)}</div>
                <div className="num mt-1 text-[12px] text-slate-500">p90 {dur(l.p90_s)} · n = {l.n} (30 dagen)</div>
              </div>
            ))}
          </section>

          <Timeline admin={admin} />

          <Panel title="Verwerking in twaalf stappen" action={<span className="caption">{data.latency.note}</span>}>
            <ol className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-[12.5px] sm:grid-cols-3 lg:grid-cols-6">
              {STEPS.map((s, i) => (
                <li key={s} className="flex items-baseline gap-2 text-slate-300"><span className="num text-[11px] text-slate-600">{String(i + 1).padStart(2, "0")}</span>{s}</li>
              ))}
            </ol>
          </Panel>

          <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
            <Panel title="Gebeurtenissen" action={<Segmented label="Weergave" value={view} onChange={setView}
              options={[["signals", `Signalen ≥ ${pct(data.signal_threshold, 0)}`], ["all", `Alles · ${items.length}`], ["dupes", "Duplicaten"]]} />}>
              {rows.length === 0 ? (
                <Empty>{items.length === 0
                  ? "Nog geen nieuws opgeslagen. Zonder bereikbare feed blijft dit leeg: er wordt niets verzonnen."
                  : "Geen items in deze weergave."}</Empty>
              ) : (
                <ul className="divide-y divide-white/[.05]">
                  {rows.slice(0, 40).map((n) => <NewsRow key={n.id} n={n} threshold={data.signal_threshold} />)}
                </ul>
              )}
            </Panel>
            <div className="space-y-5">
              <Panel title="Bronnen">
                <ul className="space-y-2.5 text-[13px]">
                  {data.feeds.map((f) => {
                    const st = typeof f.status === "object" && f.status ? f.status : null;
                    const s = st?.status ?? "not_configured";
                    return (
                      <li key={f.key} className="flex gap-2.5">
                        <span className="mt-1.5"><StatusDot status={s === "ok" ? "ok" : st ? "down" : "not_configured"} /></span>
                        <div className="min-w-0"><div className="text-slate-200">{f.name}</div>
                          <div className="truncate text-[11.5px] text-slate-500" title={st?.error}>{f.kind} · {st ? (s === "ok" ? `${st.new ?? 0} nieuw` : st.error ?? s) : "nog niet opgehaald"}</div></div>
                      </li>
                    );
                  })}
                </ul>
              </Panel>
              <Panel title="Event study" action={<span className="caption">koersreactie in σ, dag 1</span>}>
                {data.event_study.length ? (
                  <ul className="space-y-2.5 text-[12.5px]">
                    {data.event_study.slice(0, 10).map((e) => (
                      <li key={e.category + e.symbol}>
                        <div className="flex justify-between"><span className="text-slate-200">{e.category} · {e.symbol}</span>
                          <span className="num text-slate-400">{num(e.mean_z, 2)}σ · n {e.events}</span></div>
                        <div className="text-slate-500">{e.conclusion}{e.mean_z_ci95 ? ` · 95%: ${num(e.mean_z_ci95[0], 2)} tot ${num(e.mean_z_ci95[1], 2)}` : ""}</div>
                      </li>
                    ))}
                  </ul>
                ) : <Empty>Nog geen koersreacties gemeten. Een event study heeft per categorie minstens acht gebeurtenissen nodig.</Empty>}
                <p className="mt-3 text-[11.5px] leading-relaxed text-slate-500">Nieuws wordt pas een handelsregel als het effect buiten de steekproef standhoudt. &ldquo;Het taalmodel zegt bullish&rdquo; is nooit een reden.</p>
              </Panel>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function NewsRow({ n, threshold }: { n: Item; threshold: number }) {
  const [open, setOpen] = useState(false);
  const sig = (n.relevance ?? 0) >= threshold && n.duplicate_of == null;
  return (
    <li className="py-3">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="w-full text-left">
        <div className="flex items-start gap-3">
          <span className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${sig ? "bg-cyan-300" : "bg-slate-600"}`} />
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] text-slate-100">{n.title}</div>
            <div className="mt-0.5 text-[11.5px] text-slate-500">
              {n.source} · {ago(n.published_at)} · {n.category}{n.assets?.length ? ` · ${n.assets.join(", ")}` : ""}
              {n.duplicate_of != null && ` · duplicaat van #${n.duplicate_of}`}
            </div>
          </div>
          <div className="num shrink-0 text-right text-[12px]">
            <div className={sig ? "text-cyan-300" : "text-slate-500"}>{n.relevance != null ? pct(n.relevance, 0) : "—"}</div>
            <div className="text-slate-600">{n.factuality ?? ""}</div>
          </div>
        </div>
      </button>
      {open && (
        <div className="fade-up mt-3 grid gap-4 pl-[18px] text-[12.5px] md:grid-cols-2">
          <div>
            <div className="caption mb-1">Feiten</div>
            {n.facts.length ? <ul className="space-y-1 text-slate-300">{n.facts.map((f, i) => <li key={i}>· {f}</li>)}</ul> : <div className="text-slate-500">geen harde feiten herkend</div>}
            {n.expectation && !n.expectation.available && <div className="mt-2 text-slate-500">Verwachting: {n.expectation.reason ?? "niet beschikbaar"}</div>}
          </div>
          <div>
            <div className="caption mb-1">Tijdlijn</div>
            <dl className="num grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-400">
              <dt>gepubliceerd</dt><dd>{new Date(n.published_at).toLocaleString("nl-NL")}</dd>
              <dt>binnen</dt><dd>{new Date(n.fetched_at).toLocaleString("nl-NL")}</dd>
              <dt>geanalyseerd</dt><dd>{n.analyzed_at ? new Date(n.analyzed_at).toLocaleString("nl-NL") : "—"}</dd>
              <dt>signaal</dt><dd>{n.signal_at ? new Date(n.signal_at).toLocaleString("nl-NL") : "geen"}</dd>
            </dl>
            <a href={n.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-cyan-300 hover:text-cyan-200">Originele bron</a>
          </div>
        </div>
      )}
    </li>
  );
}

interface WfStep { step: string; agent: string; status: string; at: string; ms?: number; detail: Record<string, unknown> }
interface Wf {
  id: number; trace_id: string; news_id: number; status: string; simulated: boolean; source: string; title: string; url: string;
  published_at: string; detected_at: string; finished_at: string | null; cost_usd: number; steps: WfStep[];
  intelligence: { what_happened: string; assets: string[]; confirmed: string; new_information: boolean; market_expectation: string;
    already_reacted: Record<string, [number | null, number | null]>; enough_evidence_for_research: boolean; evidence_note: string;
    missing: string[]; research_priority: string };
}
const STEP_NL: Record<string, string> = {
  validate: "Tijd", deduplicate: "Ontdubbelen", classify: "Classificatie", social: "Sociaal", market: "Markt",
  research: "Onderzoeker", challenge: "Uitdager", quant: "Quant", risk: "Risk", central: "Central", explain: "Uitleg",
};
const ST_DOT: Record<string, string> = { ok: "ok", warning: "degraded", duplicate: "disabled", not_applicable: "disabled", unavailable: "not_configured", skipped: "not_configured" };

function Timeline({ admin }: { admin: ReturnType<typeof useAdmin> }) {
  const { data, refresh } = useApi<{ items: Wf[]; total: number; ai_per_day: number }>("/api/workflows?limit=12", 60_000);
  const [sel, setSel] = useState<number | null>(null);
  const w = data?.items.find((x) => x.id === sel) ?? data?.items[0];
  return (
    <Panel title="News Impact Timeline · één spoor per gebeurtenis"
      action={<div className="flex items-center gap-3"><span className="caption">{data ? `${data.total} sporen · max ${data.ai_per_day} met AI per dag` : ""}</span>
        <Btn disabled={!admin.token || !!admin.busy} onClick={() => admin.post("/api/workflows/run", {}, refresh)}>Open signalen verwerken</Btn></div>}>
      {!data ? <Skeleton className="h-48" /> : !data.items.length ? <Empty>Nog geen sporen. Elk signaal krijgt een eigen spoor: bron → markt → onderzoeker → uitdager → quant → risk → Central. Zonder echte feeds blijft dit leeg.</Empty> : (
        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          <ul className="space-y-1 text-[12.5px]">
            {data.items.map((x) => (
              <li key={x.id}><button onClick={() => setSel(x.id)} className={`w-full rounded-md px-2.5 py-2 text-left ${w?.id === x.id ? "bg-white/[.06]" : "hover:bg-white/[.03]"}`}>
                <div className="line-clamp-2 text-slate-200">{x.title}</div>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">{x.source} · {ago(x.published_at)}{x.simulated && <TruthTag kind="simulated" />}</div>
              </button></li>
            ))}
          </ul>
          {w && (
            <div className="min-w-0 text-[12.5px]">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="font-mono text-[11.5px] text-slate-500">{w.trace_id}</span>
                {w.simulated && <TruthTag kind="simulated" />}
                <span className="text-slate-400">prioriteit onderzoek: <span className="text-white">{w.intelligence.research_priority}</span></span>
                <span className="text-slate-500">· geen handelsadvies · kosten ${num(w.cost_usd, 3)}</span>
              </div>
              <ol className="mt-3 flex flex-wrap gap-1.5">
                {w.steps.map((s, i) => (
                  <li key={i} title={JSON.stringify(s.detail).slice(0, 300)} className="inline-flex items-center gap-1.5 rounded-md border border-white/[.07] px-2 py-1">
                    <StatusDot status={ST_DOT[s.status] ?? "down"} /><span className="text-slate-300">{STEP_NL[s.step] ?? s.step}</span>
                    <span className="text-[10.5px] text-slate-500">{s.status}</span>
                  </li>
                ))}
              </ol>
              <dl className="mt-4 grid gap-x-6 gap-y-2.5 md:grid-cols-2">
                {([
                  ["Wat gebeurde er", w.intelligence.what_happened],
                  ["Bevestigd", w.intelligence.confirmed],
                  ["Instrumenten", w.intelligence.assets.join(", ") || "geen"],
                  ["Nieuw", w.intelligence.new_information ? "ja" : "nee (duplicaat)"],
                  ["Verwachting markt", w.intelligence.market_expectation],
                  ["Al gereageerd", Object.entries(w.intelligence.already_reacted ?? {}).map(([k, [b, a]]) => `${k}: 5d vooraf ${b == null ? "—" : pct(b, 1)}, dag na ${a == null ? "nog niet" : pct(a, 1)}`).join(" · ") || "geen koersdata"],
                  ["Genoeg bewijs voor onderzoek", `${w.intelligence.enough_evidence_for_research ? "ja" : "nee"} · ${w.intelligence.evidence_note ?? ""}`],
                  ["Ontbreekt", w.intelligence.missing.join("; ")],
                ] as const).map(([k, v]) => <div key={k}><dt className="caption">{k}</dt><dd className="mt-0.5 text-slate-200">{v}</dd></div>)}
              </dl>
              <div className="num mt-3 text-[11.5px] text-slate-500">gepubliceerd {new Date(w.published_at).toLocaleString("nl-NL")} · binnen {new Date(w.detected_at).toLocaleString("nl-NL")} · verwerkt {w.finished_at ? new Date(w.finished_at).toLocaleString("nl-NL") : "—"} · <a href={w.url} target="_blank" rel="noreferrer" className="text-cyan-300">bron</a></div>
              <p className="mt-2 text-[12px] text-slate-400">{String(w.steps.find((s) => s.step === "explain")?.detail.text ?? "")}</p>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
