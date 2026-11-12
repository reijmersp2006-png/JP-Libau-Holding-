"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { KillStatus } from "@/lib/types";

/** Noodstop: twee klikken (geen browser-popup), daarna gaat geen enkele order meer uit,
 *  ook niet bij de paper-bot van de holding. Opheffen kan alleen met het admin-token. */
export function KillSwitch({ status, onChange }: { status: KillStatus; onChange: () => void }) {
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function engage() {
    setBusy(true); setErr(null);
    try {
      await api("/api/controls/kill", { method: "POST", body: JSON.stringify({ reason: "noodstop via Command Center" }) });
      onChange(); window.dispatchEvent(new Event("nexus:controls"));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); setArming(false); }
  }

  if (status.engaged) {
    return (
      <div className="rounded-xl border border-rose-500/50 bg-rose-500/10 p-3">
        <div className="flex items-center gap-2 font-semibold text-rose-200"><span className="pulse-dot h-2 w-2 rounded-full bg-rose-500" />NOODSTOP ACTIEF</div>
        <p className="mt-1 text-xs text-rose-200/70">Er gaat geen enkele order uit. Opheffen via Risk Guardian met het admin-token.</p>
        {status.reason && <p className="mt-1 text-xs text-slate-400">Reden: {status.reason}</p>}
      </div>
    );
  }
  return (
    <div>
      {!arming ? (
        <button onClick={() => setArming(true)}
          className="w-full rounded-xl border border-rose-500/40 bg-rose-500/[.07] px-3 py-2.5 text-sm font-semibold tracking-wide text-rose-200 transition hover:bg-rose-500/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-rose-400">
          NOODSTOP
        </button>
      ) : (
        <div className="flex gap-2">
          <button onClick={engage} disabled={busy}
            className="flex-1 rounded-xl bg-rose-600 px-3 py-2.5 text-sm font-bold text-white transition hover:bg-rose-500 disabled:opacity-60">
            {busy ? "Bezig…" : "Bevestig: alles stoppen"}
          </button>
          <button onClick={() => setArming(false)} className="rounded-xl border border-slate-700 px-3 text-sm text-slate-300 hover:border-slate-500">Annuleer</button>
        </div>
      )}
      {err && <p role="alert" className="mt-2 text-xs text-rose-300">{err}</p>}
    </div>
  );
}
