import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Backtesting Studio", phase: 4,
    purpose: "Walk-forward, out-of-sample, Monte Carlo en parametergevoeligheid, met realistische kosten en onzekerheidsmarges.",
    existing: ["Walk-forward-backtest met kosten en slippage per afdeling (jplh backtest)", "Afdelingen-backtest als spelregel voor elke wijziging (jplh backtest --desks)", "Point-in-time data: elke koers bewaart wanneer hij werd opgehaald", "Toeval-toets met blok-bootstrap (Academie)"],
    next: ["Backtests starten en bekijken vanuit NEXUS", "Monte Carlo en betrouwbaarheidsintervallen op Sharpe en rendement", "Parametergevoeligheid (heatmaps)", "Regime-vergelijking en benchmark-vergelijking per strategie", "Survivorship-controle bij aandelenuniversum"],
  }} />;
}
