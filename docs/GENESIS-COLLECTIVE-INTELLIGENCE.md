# GENESIS · Collectieve intelligentie (E1.2 – E1.4)

Code: `nexus/backend/nexus/genesis.py` (workflow), `genesis_api.py` (API), `web/app/research` (CEO Control Center).

## E1.2 Onderzoeksworkflow via NEXUS Central

Een opdracht (onderwerp, vraag, variant) loopt door een vaste statusmachine. Elke stap legt vast: agent, aanbieder,
model, bewijs-ids, tijdstip, duur, besluit, kosten, status en details.

| # | Stap | Rol | Soort |
|---|---|---|---|
| 1 | `intake`: vraag, variant, kostenplan vooraf, resterend budget, pauze | NEXUS Central (CIO) | vaste code |
| 2 | `market_context` | Market Regime | gemeten |
| 3 | `technical`: trend, RSI, volatiliteit, drawdown, 52-weeks bereik | Technical | gemeten |
| 4 | `quant`: basiskans 28 dagen, voorwaardelijk op SMA200, 95%-interval, alleen data **vóór de holdout** | Quant | gemeten |
| 5 | `fundamental` (variant D, alleen met opgeslagen document) | Fundamental | AI |
| 6 | `analysis`: analist per klasse (crypto, meme, aandelen = fundamental, overig = macro) | specialist | AI of vaste regels (A) |
| 7 | `challenge_rules`: vaste controles | Strategy Auditor | vaste code |
| 8 | `challenge` (C, D): AI-uitdaging, bij voorkeur andere aanbieder | Strategy Auditor | AI |
| 9 | `revision`: maximaal één herziening als er ernstige bevindingen zijn | analist | AI |
| 10 | `risk`: limieten, blootstelling, volatiliteit; nooit een order | Risk Guardian | vaste code |
| 11 | `risk_review` (D) | Risk Guardian | AI, alleen tekst |
| 12 | `synthesis`: conclusie | CIO | vaste regels |
| 13 | `ledger`: voorspellingen registreren | Model Evaluation | vaste code |
| 14 | escalatie naar de CEO als de aanbeveling dat vraagt | CIO → CEO | takenwachtrij |

Varianten: **A** alleen vaste code, **B** één analist, **C** analist + uitdager, **D** volledige Council.

Grenzen: maximaal 14 stappen, 300 seconden, één herziening, een kostenplan vooraf dat in het resterende budget moet
passen, een harde grens per run (`NEXUS_GENESIS_MAX_RUN_USD`, standaard $5) en maximaal 10 opdrachten per dag
(`NEXUS_RESEARCH_PER_DAY`, geteld in de database). Zonder aanbieder wordt een AI-stap **BLOCKED** en valt de analyse terug
op vaste regels; dat staat zichtbaar in de conclusie (`fallback_deterministic`) en kan nooit "hoog vertrouwen" opleveren.

## E1.3 Samenwerkingsprotocol

Elke overdracht is een bericht met vaste velden: `from`, `to`, `purpose`, `question`, `findings`, `evidence`,
`assumptions`, `uncertainties`, `contradictions`, `next`, `at`. Overdrachten worden opgeslagen bij de opdracht en geteld
in de Neural Core (lijn per rolpaar, geel als er een echte AI-stap in zat).

## E1.3 Onafhankelijke uitdager

Vaste controles (`check_analysis`) draaien **altijd**, ook zonder AI:

| Soort | Wat wordt gezocht |
|---|---|
| `unknown_reference` | bewijs-id dat niet in de feitenlijst staat |
| `unsupported_claim` | bewering zonder geldig bewijs |
| `missing_evidence` | geen enkele onderbouwde bewering |
| `calculation` | getal dat niet klopt met het feit waarnaar het verwijst (met tolerantie) |
| `data_leakage` | verwijzing naar een feit van na het peilmoment (de quant-feiten zelf gebruiken alleen data vóór de holdout) |
| `overfitting` | prestatieclaim zonder verwijzing naar een gemeten toets (`quant:`-feit) |
| `conflicting_sources` | kans die tegen de gemeten 30- en 90-daagse richting ingaat zonder uitleg |
| `overconfidence` | stellige taal of hoge zekerheid met weinig bewijs, of geen onzekerheden genoemd |

De AI-uitdager gebruikt hetzelfde vocabulaire (plus `unsupported_assumption` en `alternative`) en levert bezwaren,
alternatieve verklaringen en een eigen vertrouwen. Hij vraagt eerst een **andere aanbieder** dan de auteur; lukt dat
niet, dan staat `independent_provider: false` in de conclusie. Hetzelfde model twee keer is geen onafhankelijke toets.

**Vangt hij echt fouten?** Op een vaste set van 14 gevallen (3 schoon, 11 met een geplante fout) vinden de vaste controles
**11 van 11** geplante fouten en geven ze **0 van 3** valse alarmen (`GET /api/genesis/eval`, set-hash in het scherm).
Beperking: deze set is synthetisch en door de ontwikkelaar geschreven. Hij toetst het mechaniek, niet de vangst in echte
modeluitvoer. Dat volgt pas uit de vergelijking A–D met echte aanroepen en de blinde CEO-beoordeling.

## E1.4 Consensus op bewijs, meningsverschillen bewaard

De conclusie (`synthesize`) neemt alleen beweringen over met geldige bron-ids en zonder ernstige bevinding of bezwaar.
Velden: hoofdhypothese, onderbouwing met ids, tegenargumenten, kwantitatieve bevindingen, fundamentals, vertrouwen,
ontbrekende informatie, risico's, aanbeveling, escalatie, **meningsverschillen**, uitdaging, data-label.

- Vertrouwen is een **regel**, geen gevoel: laag bij een ernstige bevinding of minder dan 2 onderbouwde beweringen; hoog
  alleen met minstens 3, zonder ernstig bezwaar en niet bij een terugval op vaste code.
- Een ernstige bevinding verlaagt de aanbeveling (`further_research` of `escalate_to_ceo` wordt `monitor`).
- Meningsverschillen worden nooit weggepoetst: elk bezwaar van de uitdager en elke afwijking van ≥ 0,15 van de
  historische basiskans wordt opgeslagen met beide standpunten en het bewijs.
- Elke conclusie zegt: onderzoek, geen handelsadvies. Orders gaan altijd via de Risk Guardian en de CEO; live staat uit.

## Waar het te zien is

| Plek | Wat |
|---|---|
| `/research` (CEO Control Center) | aanvragen met kostenraming, status, stappen, bewijs, conclusie, meningsverschillen, overdrachten, ledger, evaluatie, kosten, storingen, gereedheid, pauze |
| `/decisions` (Decision Theater) | onderzoekssporen met per stap agent, model, bewijs, tijdstip, besluit, kosten en status |
| `/hq` (Neural Core) | overdrachten uit onderzoek, AI-gebruik per lijn, lopend / afgerond / geblokkeerd, aanbiederfouten, meningsverschillen |
| CEO Copilot | de zeven vragen uit de opdracht, beantwoord uit records met bron-ref (`research:<trace>`) |

## Stand

| Onderdeel | Gate 1 | Gate 2 | Gate 3 |
|---|---|---|---|
| Workflow, protocol, consensus | TESTED | CONNECTED voor de vaste-code-stappen op opgeslagen data; AI-stappen BLOCKED | nog niet gemeten |
| Onafhankelijke uitdager, vaste controles | TESTED (11/11, 0 vals alarm, synthetisch) | CONNECTED | niet gevalideerd op echte modeluitvoer |
| Onafhankelijke uitdager, AI | TESTED met nep-adapters | BLOCKED | — |
