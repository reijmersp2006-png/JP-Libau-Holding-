import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Strategy Lab", phase: 4,
    purpose: "Strategieën bouwen, versioneren en configureren. Elke strategie is los te testen en heeft een versie.",
    existing: ["Trend, momentum, uitbraak, terugkeer naar gemiddelde en koop-en-houd (jplh.strategies)", "Weekkeuze per instrument op 500 dagen, na kosten", "Schaduw-arena: 8 uitdagers per afdeling op papier"],
    next: ["Strategie-register met versies en parameters in de database", "Volatiliteitsregime, cross-asset relatieve sterkte, risk-parity herverdeling", "Meme-momentum alleen met strenge liquiditeitsfilters", "Funding/basis-onderzoek (alleen onderzoek)"],
  }} />;
}
