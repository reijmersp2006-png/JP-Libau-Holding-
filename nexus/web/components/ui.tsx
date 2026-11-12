import type { ReactNode } from "react";
import type { DataLabel } from "@/lib/types";

const LABEL_STYLE: Record<DataLabel, string> = {
  LIVE: "text-emerald-300 border-emerald-400/40 bg-emerald-400/10",
  DELAYED: "text-cyan-300 border-cyan-400/30 bg-cyan-400/10",
  HISTORICAL: "text-amber-300 border-amber-400/30 bg-amber-400/10",
  SIMULATED: "text-violet-300 border-violet-400/30 bg-violet-400/10",
  UNAVAILABLE: "text-slate-400 border-slate-500/30 bg-slate-500/10",
};
const LABEL_HELP: Record<DataLabel, string> = {
  LIVE: "Streaming koers, minder dan een minuut oud",
  DELAYED: "Echte koers, ververst per uur, binnen de versheidsgrens",
  HISTORICAL: "Echte koers, maar ouder dan de versheidsgrens",
  SIMULATED: "Paper trading of demo: geen echt geld",
  UNAVAILABLE: "Geen data beschikbaar",
};

export function DataBadge({ label, className = "" }: { label: DataLabel; className?: string }) {
  return (
    <span title={LABEL_HELP[label]}
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[9.5px] font-semibold tracking-wider ${LABEL_STYLE[label]} ${className}`}>
      {label === "LIVE" && <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />}
      {label}
    </span>
  );
}

export function Panel({ title, label, action, children, className = "", glow = false }: {
  title?: string; label?: DataLabel; action?: ReactNode; children: ReactNode; className?: string; glow?: boolean;
}) {
  return (
    <section className={`panel fade-up p-4 ${glow ? "panel-glow" : ""} ${className}`}>
      {(title || label || action) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {title && <h2 className="eyebrow">{title}</h2>}
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
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-slate-800 ${className}`}
      role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)}>
      <div className={`h-full rounded-full ${color} transition-[width] duration-700`} style={{ width: `${v * 100}%` }} />
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-700/60 px-3 py-5 text-center text-sm text-slate-500">{children}</div>;
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
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${c} ${status === "ok" ? "pulse-dot" : ""}`} />;
}

export function PageTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
        {sub && <p className="mt-1 max-w-3xl text-sm text-slate-400">{sub}</p>}
      </div>
      {right}
    </div>
  );
}
