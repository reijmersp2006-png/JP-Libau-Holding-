import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Execution Monitor", phase: 5,
    purpose: "Orderlevenscyclus, vullingen, slippage tegen verwachting, reconciliatie en rate-limits.",
    existing: ["Paper-broker vult tegen de laatste koers met kosten en slippage", "Alle vullingen in de boekhouding per afdeling"],
    next: ["Order-statussen (nieuw, deels gevuld, gevuld, geannuleerd)", "Idempotente orders en dubbele-orderpreventie", "Reconciliatie met de broker", "Handelsstops en circuit breakers zichtbaar", "Live adapters pas in fase 6, na expliciete activatie"],
  }} />;
}
