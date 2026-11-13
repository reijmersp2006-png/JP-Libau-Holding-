import { Workstation } from "@/components/Workstation";

export default function Page() {
  return <Workstation classes={["fx", "context"]} title="Valuta" initial="EURUSD=X"
    intro="Valutaparen met dagkoersen sinds 2021 en beperkte uurkoersen. Als macrocontext zijn de dollarindex, de Amerikaanse 10-jaarsrente en de VIX te vergelijken. Een macrokalender met consensusverwachtingen is niet gekoppeld." />;
}
