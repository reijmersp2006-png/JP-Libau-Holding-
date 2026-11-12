export function EnvBanner({ env }: { env: "demo" | "paper" | "unconfigured" }) {
  if (env === "demo") {
    return (
      <div className="mb-4 rounded-xl border border-violet-400/40 bg-violet-500/10 px-4 py-2.5 text-sm text-violet-100">
        <b className="tracking-wide">DEMO-OMGEVING.</b> Alle koersen en resultaten hieronder zijn nep, gemaakt om de
        interface te tonen. Ze zeggen niets over echte prestaties.
      </div>
    );
  }
  if (env === "unconfigured") {
    return (
      <div className="mb-4 rounded-xl border border-amber-400/40 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-100">
        <b>Geen holding-data gekoppeld.</b> Zet <code className="font-mono">NEXUS_HOLDING_HOME</code> op de map van de
        holding (bijv. een checkout van de <code className="font-mono">paper-data</code>-branch) of start met
        <code className="font-mono"> NEXUS_DEMO=1</code>. Tot dan tonen we geen cijfers.
      </div>
    );
  }
  return null;
}
