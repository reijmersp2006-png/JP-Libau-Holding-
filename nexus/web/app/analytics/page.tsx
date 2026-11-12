import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Analytics & Reports", phase: 4,
    purpose: "Rendement, Sharpe, Sortino, profit factor, win rate, expectancy, turnover en kosten per strategie en asset.",
    existing: ["Factsheet en weekrapport van de holding (HQ-dashboard, Jarvis)", "Backtest-rapporten in reports/"],
    next: ["Volledige prestatietabel met betrouwbaarheidsintervallen", "Live tegenover backtest per strategie", "Exporteerbare maandrapporten"],
  }} />;
}
