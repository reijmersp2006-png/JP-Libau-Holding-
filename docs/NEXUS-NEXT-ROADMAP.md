# NEXUS · roadmap na Milestone C

## Waar we staan

Alle onderdelen zijn met elkaar verbonden en getest, maar in de ontwikkelomgeving praat NEXUS nog met **geen
enkele** externe dienst. De grootste waarde zit nu in activeren, niet in nieuwe functies.

## Nu (configuratie, geen nieuwe code; vraagt CEO-akkoord waar het geld kost)

1. Volgende sessie in de omgeving "JP-Libau Holding NEXUS (data-feeds)".
2. `ANTHROPIC_API_KEY` op de server en de activatietest draaien. Verwachte kosten: minder dan $0,05 per test.
3. `NEXUS_SEC_USER_AGENT` zetten, nieuws ophalen en controleren dat feeds op CONNECTED staan.
4. Echte koppen labelen tot 50 testitems.
5. `NEXUS_OPERATOR_TOKEN` voor operators.

## Daarna: meten (2 tot 4 weken echte data)

- Event study per nieuwscategorie (minimaal 8 gebeurtenissen per categorie).
- Arena op `news-ceo-v1`: vaste regels tegen elk model, met kosten per correct label.
- Kalibratie van Council-voorspellingen zodra er 30 zijn afgerekend.
- De beschermde holdout blijft onaangeroerd tot de afgesproken einddatum.

## Milestone D (na CEO-goedkeuring)

Institutioneel ontwerp volgens [INSTITUTIONAL-DESIGN-D-PLAN.md](INSTITUTIONAL-DESIGN-D-PLAN.md), te beginnen met het
Executive Command Center en het Decision Theater.

## Milestone E (na CEO-goedkeuring; niet eerder)

- Gebruikersaccounts met rollen, MFA, sessies en intrekbare tokens (plan in ASCENSION-C-ACTIVATION.md §C6).
- Een tweede AI-aanbieder voor echt onafhankelijke debatten.
- X alleen na een besluit over een betaald plan.

## Blijft altijd zo

Live trading UIT, geen hefboom, geen autonome strategieën, geen limietwijzigingen door agenten. Elke toekomstige
uitvoering loopt via de Risk Guardian en een goedgekeurde gateway. Er worden geen data, resultaten of verbindingen
verzonnen.
