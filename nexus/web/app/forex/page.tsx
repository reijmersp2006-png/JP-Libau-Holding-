import { Placeholder } from "@/components/Placeholder";

export default function Page() {
  return <Placeholder spec={{
    title: "Forex Terminal", phase: 2,
    purpose: "Valutaparen, renteverschillen, macro-agenda en spreads per sessie. Omwisselen staat los van speculatieve FX-handel.",
    existing: ["EUR/USD, EUR/GBP, EUR/JPY uurkoersen (Yahoo, DELAYED)", "Officiële ECB-referentiekoersen", "Valuta-afdeling: aanhouden van vreemde munt, zonder hefboom"],
    next: ["Renteverschillen per paar", "Economische kalender met event-risico", "Sessie-liquiditeit (Azië/Europa/VS)", "Correlatiematrix van valuta"],
    sources: ["ECB Data Portal (gratis)", "Economische kalender: Trading Economics of FRED (FRED gratis met sleutel)"],
  }} />;
}
