const nl = "nl-NL";

export const eur = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toLocaleString(nl, { style: "currency", currency: "EUR", minimumFractionDigits: digits, maximumFractionDigits: digits });

export const usd = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString(nl, { style: "currency", currency: "USD", notation: v >= 1e6 ? "compact" : "standard", maximumFractionDigits: v < 1 ? 8 : 2 });

export const pct = (v: number | null | undefined, digits = 2, signed = false) =>
  v == null ? "—" : `${signed && v > 0 ? "+" : ""}${(v * 100).toLocaleString(nl, { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;

export const num = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toLocaleString(nl, { maximumFractionDigits: digits });

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "nooit";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "zojuist";
  if (s < 3600) return `${Math.round(s / 60)} min geleden`;
  if (s < 86400) return `${Math.round(s / 3600)} uur geleden`;
  return `${Math.round(s / 86400)} dagen geleden`;
}

export const time = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(nl, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

export const tone = (v: number | null | undefined) =>
  v == null || Math.abs(v) < 1e-12 ? "text-slate-300" : v > 0 ? "text-emerald-400" : "text-rose-400";
