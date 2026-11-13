import { Workstation } from "@/components/Workstation";

export default function Page() {
  return <Workstation classes={["stocks", "metals", "context"]} title="Aandelen, ETF's en grondstoffen" initial="IWDA.AS"
    intro="Vertraagde dagkoersen sinds 2020 (Yahoo, onofficieel) en een beperkte reeks uurkoersen. Jaarcijfers en een winstkalender ontbreken tot er een aandelenbron is gekozen. Het IWDA-onderzoek blijft negatief ten opzichte van kopen en vasthouden." />;
}
