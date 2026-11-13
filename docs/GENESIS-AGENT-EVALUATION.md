# GENESIS · Agent-evaluatie (E1.5, sectie 7)

Code: `nexus/backend/nexus/genesis_eval.py`, `ledger.py`. Scherm: `/research#evaluatie` en `/research#ledger`.

## Maatstaven en waar ze vandaan komen

| Maatstaf uit de opdracht | Hoe gemeten | Bron |
|---|---|---|
| Juistheid van bewijs | aandeel beweringen met geldige bron-ids; `unknown_reference` telt als fout | `check_analysis` |
| Betrouwbaarheid van bronnen | bronlabel per feit (HISTORICAL, DELAYED, UNAVAILABLE, SIMULATED); SIMULATED telt nooit als echt | `gather` |
| Onbewezen beweringen | `unsupported_claim` per opdracht | `check_analysis` |
| Kalibratie | Brier, log loss, kalibratiebakken vanaf n ≥ 30 | `ledger.score` |
| Voltooiing | done / partial / blocked / failed per variant | `compare_arms` |
| Latentie | mediaan per variant (ms) | `compare_arms` |
| Kosten | per opdracht en per bruikbare conclusie | `/api/genesis/costs` |
| Foutdetectie | geplante fouten (benchmark) en ernstige bevindingen per variant; herstel na herziening | benchmark, `compare_arms` |
| Bruikbaarheid | blinde CEO-score 1–5 met 95%-interval | `ResearchReview` |
| Bijdrage | Brier-skill van een agent tegen de vaste basiskans | `ledger.score` |

## Bevroren referenties

- **Deterministische basislijn (A)**: alleen vaste code; altijd draaibaar en gratis.
- **Klimatologische basislijn**: bij elke opdracht registreert de ledger de historische basiskans (pre-holdout) als
  voorspelling van `baseline_climatology`. Elke AI-agent moet daar beter dan zijn (Brier-skill > 0) om iets toe te voegen.
- **Eén analist (B)**: de eenvoudigste AI-variant.

Promptversie `genesis-v1` staat bij elke stap en elke voorspelling. Een nieuwe prompt is een nieuwe versie, geen
stille wijziging.

## Vergelijking A · B · C · D

Zelfde onderwerpen, zelfde peilmoment, één kostengrens voor alles (`POST /api/genesis/eval/arms`, alleen admin, grens
≤ maximum per run). Resultaat in deze omgeving (testdatabase met de opgeslagen koersen, grens $0):

| Variant | Runs | Klaar | Geblokkeerd | Kosten |
|---|---|---|---|---|
| A · vaste code | 3 | 3 | 0 | $0 |
| B · één analist | 3 | 0 | 3 | $0 |
| C · + uitdager | 3 | 0 | 3 | $0 |
| D · volledige Council | 3 | 0 | 3 | $0 |

**Niet goed, maar eerlijk**: B, C en D zijn geblokkeerd omdat er geen sleutel is. Er is dus nog **geen enkele uitspraak**
over welke variant beter is. Regel voor later: de eenvoudigste variant wint, tenzij een complexere variant aantoonbaar
beter is (95%-interval van de bruikbaarheid boven dat van de eenvoudigere, en betere Brier-skill bij genoeg n).

## Onafhankelijke beoordeling

- **De 28/30 van de News Reactor is geen bewijs van generalisatie**: die set is geschreven door dezelfde ontwikkelaar
  als de regels. Hij blijft als regressietest, niet als kwaliteitsmaat.
- **Benchmark van de uitdager**: 11/11 geplante fouten, 0/3 vals alarm, maar synthetisch (zie
  `GENESIS-COLLECTIVE-INTELLIGENCE.md`). Toetst het mechaniek, niet de echte vangst.
- **Blinde CEO-beoordeling**: `/research#evaluatie` toont conclusies uit de vergelijking **zonder de variant**.
  De CEO geeft bruikbaarheid 1–5 en het aantal gevonden fouten. Eén beoordeling per conclusie per persoon (database-
  regel). Uitslag per variant met n en 95%-interval.
- **Labelrij voor nieuws (bestaand, Milestone C)**: echte koppen gelabeld door de CEO of operator, met een vaste
  hash-split tussen ontwikkel- en testset zodat er niet op de testset wordt bijgesteld.
- **Lekpreventie**: quant-feiten gebruiken alleen data vóór de holdout (12-11-2026); voorspellingen worden alleen
  vooruit geregistreerd met servertijd; een analyse die naar later bewijs verwijst krijgt `data_leakage`.

## Wat er nog niet is (en waarom)

- Geen Brier, kalibratie of bruikbaarheid per AI-agent: er zijn **0 AI-voorspellingen** en **0 beoordelingen**.
  Eerst echte aanroepen (activatie), daarna 28 dagen wachten tot de eerste horizon.
- Geen uitspraken uit kleine aantallen: kalibratie pas vanaf 30 afgerekende voorspellingen, bruikbaarheid met interval.
