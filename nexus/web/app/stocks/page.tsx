import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Stock Terminal", phase: 2,
    purpose: "Aandelen en ETF’s: bedrijfsprofiel, jaarcijfers, waardering, winstkalender, nieuws en sectorvergelijking.",
    existing: ["Uur- en dagkoersen van Yahoo Finance voor IWDA, ASML, AAPL, MSFT, NVDA (DELAYED, onofficiële bron)", "Aandelenafdeling: vasthouden met kwartaal-herverdeling"],
    next: ["Bedrijfsprofiel en financiële overzichten", "Winstkalender en estimate-revisies", "Waarderingsmultiples t.o.v. sector", "Beursuren- en jurisdictiechecks per markt"],
    sources: ["Fundamentele data: Financial Modeling Prep, Polygon of EODHD (betaald)", "Officiële koersbron ter vervanging van Yahoo (licentie)", "Broker voor uitvoering: bijv. Interactive Brokers of Saxo (fase 6)"],
  }} />;
}
