# NEXUS 3.1 · resultaten van het onderzoek (12 november 2026)

**Kort:** er is geen strategie gevonden die koop-en-houd op IWDA geloofwaardig verslaat. Eén aanpassing aan de
bestaande strategie (minder handelen, *volatiliteitsfilter v2*) is aantoonbaar beter dan het origineel, maar
blijft achter bij gewoon vasthouden. Het systeem om dat te meten, te leren en te bewaken staat er nu wel.

Alle cijfers komen uit echte dagkoersen van de holding (`data/holding.sqlite3`, IWDA vanaf 2022), gerekend op
€1000 met de kostenmodellen van de holding (vaste fee met minimum, halve spread, slippage). Uitvoering op de
open van de volgende dag. Geen hefboom, geen short. Niets hiervan is live gehandeld.

## Wat er veranderde en waarom

| Mijlpaal | Wat | Waarom |
|---|---|---|
| Diagnose | attributie van het verschil met koop-en-houd, causaliteitstoets, datakwaliteit, gevoeligheid | eerst begrijpen waarom +7,2% tegen +30,3%, vóór iets aan te passen ([IWDA-DIAGNOSE.md](IWDA-DIAGNOSE.md)) |
| IJkpunt | de oude uitkomsten van alle 90 combinaties bewaard ([baselines/](baselines/)) | niets overschrijven voordat het origineel is vastgelegd |
| Statistiek | blok-bootstrap, probabilistische en gedefleerde Sharpe, Monte Carlo-daling | een hoger getal is pas iets waard als de onzekerheid erbij staat |
| Alpha Research Engine | 12 strategiefamilies, walk-forward per vak, laatste 20% afgesloten als holdout, holdout-register | zoeken zonder op de testdata af te stemmen |
| Arena | kampioen tegen uitdagers met 8 poorten | geen enkele wijziging zonder toets tegen kampioen, koop-en-houd en risico-gematcht alternatief |
| Evolution | besluitgeheugen, foutpatronen, hypothesen, toets, modelregister | leren moet een meetbare wijziging opleveren, niet een verhaal |
| Council, nieuws, Grok-vergelijking, taken | zie [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) | infrastructuur; nog zonder trackrecord |

## Uitkomsten

### 1. Ontdekking (alle families, alle instrumenten, dagdata, alleen ontwikkelperiode)

179 combinaties, 1469 geteste instellingen. **0 kandidaten** door de ontwikkelpoorten. De holdout is daarom
nergens geopend en blijft onaangeroerd.

### 2. Arena IWDA (walk-forward 1 nov 2023 tot 9 sep 2025; holdout vanaf 9 sep 2025, dicht)

| | Sharpe | Rendement | Max daling | P(beter dan kampioen) | P(beter dan koop-en-houd) | Poorten |
|---|---|---|---|---|---|---|
| Koop-en-houd | 1,27 | +37,7% | 22,5% | | | |
| Kampioen: volatiliteitsfilter v1 | 0,50 | +5,1% | | | | |
| Bevestigde uitbraak | 1,31 | +19,3% | 5,8% | 88% | 47% | 3 van 8 |
| Volatiliteitsfilter v2 | 1,21 | +16,0% | 8,0% | 97% | 42% | 2 van 8 |
| Volatiliteitsdoel | 0,98 | +25,0% | 22,1% | 73% | 1% | 1 van 8 |

*Bevestigde uitbraak* heeft de hoogste Sharpe, maar dat is binnen de ruis (47% kans dat hij beter is dan
koop-en-houd), hij deed maar 5 afgeronde trades, en maar 12% van de naburige instellingen versloeg koop-en-houd. Geen uitdager komt door poort 6, dus
geen enkele mag naar de holdout.

### 3. Hypothesen uit de diagnose, getoetst door de leerlus

| Hypothese | Beste kandidaat | Sharpe (bron 0,50) | P(beter dan bron) | P(beter dan koop-en-houd) | Uitkomst |
|---|---|---|---|---|---|
| A. kleiner in plaats van eruit | volatiliteitsdoel 20% | 0,98 | 73% | 1% | onbeslist |
| B. minder handelen | volfilter v2 (kwantiel 0,7, min. 20 dagen) | 1,21 | **97%** | 42% | **gesteund** |
| C. risico-gematchte maatlat | trendsterkte 50/100 | 0,47 | 51% | 1% | onbeslist |
| D. rotatie in plaats van cash | regimewissel (IWDA/IEAG/XEON) | 0,85 | 64% | 23% | onbeslist |

Hypothese B is als kandidaat in het modelregister gezet. Promoveren naar paper wordt door de server
geweigerd: poorten 2, 3, 5 en 6 zijn niet gehaald.

De leerlus las 22 echte besluiten van de holding in, herhaalde de strategie 54 keer op historie en vond
5 gemiste stijgingen (gemiddeld +8,8% in de 20 dagen erna buiten de markt).

## Beoordeling volgens de 3.1-vragen

- **Verbeterde out-of-sample?** Ja, ten opzichte van het origineel: v2 haalt Sharpe 1,21 tegen 0,50 op dezelfde
  walk-forward-vakken.
- **Statistisch geloofwaardig?** Tegenover het origineel redelijk (97%, blok-bootstrap). Tegenover koop-en-houd
  niet (42%), en maar 56% van de naburige instellingen doet het beter dan koop-en-houd, dus de uitkomst hangt
  aan de gekozen instelling. De periode is kort (twee jaar walk-forward, één markt in een stijgende fase).
- **Nog achter koop-en-houd?** Ja. +16,0% tegen +37,7% rendement, met een kleinere daling (8% tegen 22,5%).
  Risico-gematcht (koop-en-houd geschaald naar dezelfde beweeglijkheid) is het verschil −0,5% per jaar: geen voordeel.
- **Eerlijke conclusie:** voor IWDA is vasthouden nog steeds de beste regel. De lab-strategie kan beter worden
  gemaakt, maar niet beter dan vasthouden.

## Wat er nog niet kan, en wat als volgende te onderzoeken

1. **Meer geschiedenis.** IWDA vanaf 2022 is te kort: na opwarmen blijven er twee jaar walk-forward over. Langere
   dagreeksen en 1h/4h-data ophalen (in GitHub Actions werkt het netwerk; hier niet).
2. **Crypto apart onderzoeken.** In dalende crypto bleven trendfilters minder diep achter dan vasthouden, maar met
   1 tot 3 trades. De ontdekking op 4h/1h geeft genoeg trades om iets te kunnen zeggen.
3. **Funding en open interest, consensusverwachtingen.** Deze families staan op `niet beschikbaar` tot er een bron is.
4. **Council-trackrecord.** Zonder `ANTHROPIC_API_KEY` draait de Council niet. Met sleutel worden voorspellingen
   na 20 handelsdagen afgerekend; pas na 30 afgerekende voorspellingen per agent heet een gewicht gekalibreerd.
5. **Paper-trackrecord van v2** alleen als hij eerst poort 2 (beter dan koop-en-houd) haalt. Dat is nu niet zo.

Reproduceren: `nexus-research audit`, `nexus-research discover`, of in het dashboard: Evolution Lab.
