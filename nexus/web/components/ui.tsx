import type { ReactNode } from "react";
import type { DataLabel } from "@/lib/types";

const LABEL_STYLE: Record<DataLabel, string> = {
  LIVE: "text-emerald-300", DELAYED: "text-cyan-300", HISTORICAL: "text-amber-300",
  SIMULATED: "text-violet-300", UNAVAILABLE: "text-slate-500",
};
const LABEL_TEXT: Record<DataLabel, string> = {
  LIVE: "Live", DELAYED: "Vertraagd", HISTORICAL: "Historisch", SIMULATED: "Gesimuleerd", UNAVAILABLE: "Geen data",
};
const LABEL_HELP: Record<DataLabel, string> = {
  LIVE: "Streaming koers, minder dan een minuut oud",
  DELAYED: "Echte koers, ververst per uur, binnen de versheidsgrens",
  HISTORICAL: "Echte koers, maar ouder dan de versheidsgrens",
  SIMULATED: "Paper trading of demo: geen echt geld",
  UNAVAILABLE: "Geen data beschikbaar",
};

/** Herkomst van een getal: rustig, als punt + woord, niet als felle badge. */
export function DataBadge({ label, className = "" }: { label: DataLabel; className?: string }) {
  return (
    <span title={LABEL_HELP[label]}
      className={`inline-flex items-center gap-1 whitespace-nowrap text-[10.5px] font-medium ${LABEL_STYLE[label]} ${className}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${label === "LIVE" ? "pulse-dot" : "opacity-80"}`} />
      {LABEL_TEXT[label]}
    </span>
  );
}

export function Panel({ title, label, action, children, className = "", glow = false }: {
  title?: string; label?: DataLabel; action?: ReactNode; children: ReactNode; className?: string; glow?: boolean;
}) {
  return (
    <section className={`panel fade-up p-5 ${glow ? "panel-glow" : ""} ${className}`}>
      {(title || label || action) && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {title && <h2 className="title-md">{title}</h2>}
            {label && <DataBadge label={label} />}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, valueClass = "" }: { label: string; value: ReactNode; sub?: ReactNode; valueClass?: string }) {
  return (
    <div>
      <div className="eyebrow mb-1">{label}</div>
      <div className={`num text-lg font-semibold tracking-tight ${valueClass}`}>{value}</div>
      {sub && <div className="num mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function Meter({ value, warn = 0.7, className = "" }: { value: number; warn?: number; className?: string }) {
  const v = Math.max(0, Math.min(1, value));
  const color = value >= 1 ? "bg-rose-500" : value >= warn ? "bg-amber-400" : "bg-cyan-400";
  return (
    <div className={`h-1 w-full overflow-hidden rounded-full bg-white/[.06] ${className}`}
      role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)}>
      <div className={`h-full rounded-full ${color} transition-[width] duration-700`} style={{ width: `${v * 100}%` }} />
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-white/[.08] px-4 py-6 text-center text-[13px] leading-relaxed text-slate-500">{children}</div>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="panel border-rose-500/30 p-5">
      <div className="flex items-start gap-3">
        <span className="mt-1 h-2 w-2 rounded-full bg-rose-500" />
        <div className="flex-1">
          <div className="font-medium text-rose-300">Geen verbinding met de NEXUS API</div>
          <div className="mt-1 text-sm text-slate-400">{message}. Er worden geen cijfers getoond zolang er geen echte data is.</div>
          <div className="mt-2 font-mono text-xs text-slate-500">cd nexus/backend &amp;&amp; nexus-api</div>
        </div>
        {onRetry && <button onClick={onRetry} className="rounded-md border border-slate-700 px-3 py-1 text-sm hover:border-cyan-400/50">Opnieuw</button>}
      </div>
    </div>
  );
}

export function StatusDot({ status }: { status: string }) {
  const c = { ok: "bg-emerald-400", configured: "bg-cyan-400", degraded: "bg-amber-400", down: "bg-rose-500",
    disabled: "bg-slate-500", not_configured: "bg-slate-500" }[status] ?? "bg-slate-500";
  return <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${c}`} />;
}

export function PageTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="title-lg">{title}</h1>
        {sub && <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-slate-400">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

/** Grote kerncijfers met een rustige hiërarchie. */
export function Kpi({ label, value, sub, tone = "", href }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; href?: string }) {
  const body = (
    <>
      <div className="caption">{label}</div>
      <div className={`num mt-1.5 text-[22px] font-semibold leading-none tracking-tight ${tone || "text-white"}`}>{value}</div>
      {sub && <div className="num mt-1.5 text-[12px] text-slate-500">{sub}</div>}
    </>
  );
  return href ? <a href={href} className="block rounded-lg px-1 py-0.5 transition-colors hover:bg-white/[.02]">{body}</a> : <div className="px-1 py-0.5">{body}</div>;
}

/** Onderscheid tussen soorten uitspraken (4.0): geïmplementeerd, getest, verbonden, gesimuleerd, niet beschikbaar. */
export type Truth = "connected" | "simulated" | "estimate" | "unavailable" | "actual";
const TRUTH: Record<Truth, [string, string]> = {
  actual: ["Actueel", "text-emerald-300"], connected: ["Verbonden", "text-emerald-300"],
  simulated: ["Gesimuleerd", "text-violet-300"], estimate: ["Schatting", "text-amber-300"],
  unavailable: ["Niet beschikbaar", "text-slate-500"],
};
export function TruthTag({ kind, className = "" }: { kind: Truth; className?: string }) {
  const [t, c] = TRUTH[kind];
  return <span className={`inline-flex items-center gap-1 text-[10.5px] font-medium ${c} ${className}`}><span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />{t}</span>;
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex rounded-lg border border-white/[.07] bg-white/[.02] p-0.5">
      {options.map(([k, t]) => (
        <button key={k} role="tab" aria-selected={value === k} onClick={() => onChange(k)}
          className={`rounded-md px-3 py-1.5 text-[12.5px] transition-colors ${value === k ? "bg-white/[.08] text-white" : "text-slate-400 hover:text-slate-200"}`}>{t}</button>
      ))}
    </div>
  );
}
