"use client";

/**
 * NEXUS Apex-componenten (design system 6.0). Bouwt voort op ui.tsx (Panel, DataBadge, Empty, Skeleton).
 * Regels: één oppervlak per onderwerp, haarlijnen in plaats van kaartjes, cijfers tabulair,
 * herkomst en versheid altijd zichtbaar, en een eerlijke lege toestand in plaats van een mooi plaatje.
 */
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ago } from "@/lib/format";
import type { DataLabel } from "@/lib/types";
import { DataBadge } from "./ui";

export function PageHeader({ eyebrow, title, sub, right, meta }: { eyebrow?: string; title: string; sub?: ReactNode; right?: ReactNode; meta?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className="title-lg mt-1.5">{title}</h1>
        {sub && <p className="mt-2 max-w-3xl text-[13.5px] leading-relaxed text-slate-400">{sub}</p>}
        {meta && <div className="t-label mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">{meta}</div>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-3">{right}</div>}
    </header>
  );
}

/** Eén strook met kerncijfers. Elke cel: label, waarde, toelichting, optioneel herkomst en link. */
export function KpiStrip({ children, cols = "md:grid-cols-4 xl:grid-cols-7" }: { children: ReactNode; cols?: string }) {
  return <section aria-label="Kerncijfers" className={`kpi-strip fade-up grid-cols-2 ${cols}`}>{children}</section>;
}

export function KpiCell({ label, value, sub, tone = "", label2, href, wide = false }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string; label2?: DataLabel; href?: string; wide?: boolean;
}) {
  const body = (
    <>
      <div className="t-label flex items-center gap-2">{label}{label2 && <DataBadge label={label2} />}</div>
      <div className={`${wide ? "t-display mt-2" : "t-kpi mt-1.5"} ${tone}`}>{value}</div>
      {sub && <div className="t-micro num mt-1.5">{sub}</div>}
    </>
  );
  const cls = `${wide ? "col-span-2" : ""} min-w-0`;
  return href ? <Link href={href} className={`${cls} block transition-colors hover:bg-white/[.015]`}>{body}</Link> : <div className={cls}>{body}</div>;
}

/** Versheid: herkomstlabel + tijdstempel + leeftijd. Vertraagd is nooit "live". */
export function Freshness({ label, ts, note }: { label: DataLabel; ts?: string | null; note?: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-slate-500">
      <DataBadge label={label} />
      {ts && <span className="num" title={new Date(ts).toLocaleString("nl-NL")}>{new Date(ts).toLocaleString("nl-NL", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })} · {ago(ts)}</span>}
      {note && <span>{note}</span>}
    </span>
  );
}

/** Gemeten (vaste code) versus mening (taalmodel): altijd zichtbaar onderscheid. */
export function Provenance({ kind }: { kind: "measured" | "ai" | "rule" | "human" | "simulated" }) {
  const m = {
    measured: ["Gemeten", "text-slate-200 border-white/[.12]"], rule: ["Vaste regel", "text-slate-300 border-white/[.10]"],
    ai: ["AI-mening", "text-amber-200 border-amber-300/25"], human: ["CEO", "text-cyan-200 border-cyan-300/25"],
    simulated: ["Gesimuleerd", "text-violet-200 border-violet-300/25"],
  }[kind];
  return <span className={`chip ${m[1]}`}>{m[0]}</span>;
}

export function Delta({ v, digits = 1, className = "" }: { v: number | null | undefined; digits?: number; className?: string }) {
  if (v == null) return <span className={`num text-slate-500 ${className}`}>—</span>;
  const c = Math.abs(v) < 1e-9 ? "text-slate-300" : v > 0 ? "text-emerald-300" : "text-rose-300";
  return <span className={`num ${c} ${className}`}>{v > 0 ? "+" : ""}{(v * 100).toLocaleString("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%</span>;
}

/** Waarde die net veranderde licht één keer op. */
export function Tick({ value, children }: { value: unknown; children: ReactNode }) {
  const [k, setK] = useState(0);
  const first = useRef(true);
  const prev = useRef(value);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (prev.current !== value) { prev.current = value; const t = setTimeout(() => setK((x) => x + 1), 0); return () => clearTimeout(t); }
  }, [value]);
  return <span key={k} className={k ? "tick" : ""}>{children}</span>;
}

/** Toegankelijk zijpaneel: Esc sluit, focus gaat naar het paneel, achtergrond klikbaar om te sluiten. */
export function Drawer({ open, title, onClose, children, width = 460 }: { open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "Details"} tabIndex={-1}
        onClick={(e) => e.stopPropagation()} style={{ maxWidth: width }}
        className="drawer h-full w-full overflow-y-auto border-l border-white/[.08] bg-[#0C0F13] p-6 outline-none">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="title-md">{title}</div>
          <button onClick={onClose} className="btn px-2 py-1" aria-label="Sluiten">Esc</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items, label }: { value: T; onChange: (v: T) => void; items: [T, ReactNode][]; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex flex-wrap gap-1">
      {items.map(([k, t]) => (
        <button key={k} role="tab" aria-selected={value === k} onClick={() => onChange(k)}
          className={`rounded-md px-2.5 py-1 text-[12.5px] transition-colors ${value === k ? "bg-white/[.08] text-white" : "text-slate-400 hover:text-slate-200"}`}>{t}</button>
      ))}
    </div>
  );
}

/** Onbeschikbare gegevens als lijst met reden, zodat de gebruiker ziet wat er níet is. */
export function Unavailable({ items }: { items: Record<string, string> }) {
  const e = Object.entries(items);
  if (!e.length) return null;
  return (
    <ul className="space-y-1 text-[12px]">
      {e.map(([k, v]) => <li key={k} className="flex gap-2"><span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-600" /><span><span className="text-slate-300">{k}</span><span className="text-slate-500"> · {v}</span></span></li>)}
    </ul>
  );
}

export const CHART = {
  text: "#8B94A3", grid: "rgba(148,163,184,.05)", gridStrong: "rgba(148,163,184,.08)",
  up: "#4CC495", down: "#E25A64", metal: "#B9C2CF", ice: "#8CCBF2", violet: "#A79BEA", amber: "#DDB25C",
  crosshair: "rgba(185,194,207,.35)", crosshairLabel: "#232933",
};
