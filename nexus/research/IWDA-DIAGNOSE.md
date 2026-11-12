# Diagnose: waarom bleef de volatiliteitsfilter op IWDA zo ver achter?

Datum: 12 november 2026. Data: IWDA.AS dagkoersen 30-12-2020 t/m 11-11-2026 (Yahoo, 1.503 dagen,
vingerafdruk `8a0c442447c354d4`). De volledige cijfers staan in
[audits/IWDA.AS-volatility_filter-v1.md](audits/IWDA.AS-volatility_filter-v1.md). Het ijkpunt van alle
90 combinaties (18 instrumenten × 5 strategieën) staat ongewijzigd in
[baselines/lab-v1-2026-11-12.json](baselines/lab-v1-2026-11-12.json).

**Kort:** de achterstand (+7,2% tegen +30,3%) is echt, niet een rekenfout en niet alleen pech.
Ongeveer driekwart komt doordat de strategie 45% van de tijd buiten de markt zat in een vrijwel
ononderbroken stijgende markt. Een kwart komt van transactiekosten die op een account van €1.000 zwaar
wegen. Geen enkele instelling in de buurt van de parameters had out-of-sample koop-en-houd verslagen.
Het probleem zit in de opzet, niet in de afstelling.

## De tien vragen

| # | Vraag | Antwoord | Bewijs |
|---|---|---|---|
| 1 | Waarom bleef hij achter? | Vooral door buiten de markt te zitten (−15,0 van −19,5 log-procentpunt). De rest zijn kosten (−5,3). Instap en uitstap op de opening hielpen licht (+0,7). | Attributie, telt exact op |
| 2 | Stapte hij uit tijdens sterke stijgingen? | Ja. 131 van de 154 dagen buiten de markt vielen in een stijgend regime en kostten −8,4 punt. De filter op beweeglijkheid alleen al kostte −10,7 punt. | Attributie per regime en oorzaak |
| 3 | Te traag terug in de markt? | Ja. Na een uitstap duurde het gemiddeld 8,8 handelsdagen tot hij weer instapte, en dan gemiddeld 1,1% duurder dan de verkoopprijs. Dat gebeurde 11 keer. | Herinstap-analyse |
| 4 | Kostten de trades te veel? | Ja. Een heen-en-terug kost €4,50 op €1.000 (0,45%), vooral door de minimumfee van €1,25. Out-of-sample was dat €55, oftewel 5,8 procentpunt. Zonder kosten was het +13,0%, met €10.000 kapitaal +9,0%. Vijf van de twaalf trades duurden 3 dagen of korter en verloren samen €13,88, waarvan €23,01 kosten waren. | Kostenanalyse |
| 5 | Slecht afgesteld? | Niet de hoofdoorzaak. Van 9 buren lag de out-of-sample Sharpe tussen −0,06 en 0,73, en die van koop-en-houd op 1,72. De beste instelling in-sample haalde out-of-sample 0,56. De originele instelling had al in-sample een negatieve Sharpe (−0,07): hij had nooit door een toets mogen komen. | Gevoeligheid |
| 6 | Woog de lagere daling op tegen het lagere rendement? | Nee. De maximale daling was 5,1% tegen 6,5% (1,4 punt minder), voor 23,1 punt minder rendement. Calmar 0,96 tegen 3,07. | Risicoafweging |
| 7 | Paste de strategie bij IWDA? | Slecht. IWDA is een breed gespreide wereldindex met een positieve langetermijntrend. Een filter "beweeglijkheid boven de mediaan → eruit" zet je per definitie zo'n half jaar per jaar buiten de markt. Bij aandelenindexen vallen de sterke herstellen juist vaak in onrustige perioden. | Ontwerp, plus regime-attributie (23 dagen buiten de markt in een dalend regime kostten nog −6,5 punt aan gemist herstel) |
| 8 | Was de testperiode ongewoon gunstig voor koop-en-houd? | Ja, deels. Out-of-sample steeg de index 20,2% per jaar bij 11% beweeglijkheid, en 94% van de dagen viel in een stijgend regime. In-sample was dat 8,4% per jaar, over alles 14,1%. Maar over de hele periode bleef hij ook achter (+5,2% tegen +72,4%). | Context, volledige periode |
| 9 | Alleen informatie van het besluitmoment? | Ja. Op 40 besluitmomenten werd het signaal opnieuw berekend op afgekapte data: 0 verschillen. Het besluit valt op de slotkoers en wordt uitgevoerd op de volgende opening. Er is ook een test die bewust spiekende strategieën vangt. | Causaliteitscontrole |
| 10 | Kloppen koersen, dividend, valuta en uitvoering? | IWDA is accumulerend: het dividend zit al in de koers, dus de vergelijking is eerlijk. Notering in euro, dus geen omrekening nodig. Geen ongeldige koersbalken en geen sprongen boven 10%. Aannames: spread 0,10% (ruim, de echte spread van IWDA is meestal kleiner), slippage 0,05%, fee 0,05% met minimaal €1,25. | Datakwaliteit, prijsbasis |

## Onzekerheid

- Verschil per jaar −14,9%, 90%-interval −25,7% tot −5,6% (blok-bootstrap, 1.000 trekkingen).
- Kans dat de strategie per jaar beter was dan koop-en-houd: 0,8%.
- De achterstand is dus statistisch geloofwaardig. Een eventuele voorsprong is dat niet: de 95%-interval van
  de Sharpe loopt van −0,97 tot 2,27.

## Methodefouten in versie 1 (gevonden, gecorrigeerd voor nieuw onderzoek)

1. **Elke strategie had haar eigen out-of-sample periode.** De start hing af van de opwarmtijd, dus
   strategieën werden over verschillende maanden met een andere maatlat vergeleken (koop-en-houd
   +20,6% tot +36,8%). Met één gezamenlijke start (4-6-2025) is de maatlat voor allemaal +30,3%.
   `run_backtest(..., oos_start=...)` legt dat nu vast.
2. **Geen in-sample poort.** De volatiliteitsfilter verloor al in-sample en is toch out-of-sample getest
   en getoond. De Alpha Research Engine laat een kandidaat pas door als hij in de trainingsperiode iets laat zien.
3. **Kosten bij klein kapitaal.** De minimumfee maakt strategieën met veel trades op €1.000
   onbruikbaar. Onderzoek rekent nu met het echte bedrag per instrument en toont de kosten per trade
   apart.
4. **USD-aandelen werden in dollars getest**, terwijl de holding in euro rekent. Nieuw onderzoek rekent om
   met de EUR/USD-koers die op het besluitmoment al bekend was.
5. **Aanname "dividend niet aangepast" gold voor alles.** Nu per instrument: accumulerende ETF
   (totaalrendement), crypto (spot), metalen (doorlopende future, rolkosten niet meegenomen), losse
   aandelen (zonder dividend; dat benadeelt koop-en-houd licht).

## Wat de andere strategieën laten zien (zelfde periode, 4-6-2025 t/m 11-11-2026)

| Strategie | Rendement | Sharpe | Max. daling | Trades | In de markt |
|---|---|---|---|---|---|
| Koop-en-houd | +30,3% | 1,72 | 6,5% | 1 | 100% |
| Trend (50/200) | +24,8% | 1,56 | 6,5% | 0 | 83% |
| Momentum (90) | +24,9% | 1,50 | 7,3% | 3 | 89% |
| Uitbraak (55/20) | +5,9% | 0,48 | 6,3% | 5 | 73% |
| Volatiliteitsfilter | +7,2% | 0,65 | 5,1% | 12 | 55% |
| Terugkeer (RSI) | 0,0% | 0,00 | 0,0% | 0 | 0% |

Geen enkele strategie versloeg koop-en-houd op IWDA. In crypto bleven trendfilters in de dalende
markt van 2025-2026 wel minder diep achter dan vasthouden (bijvoorbeeld BTC: −4% tegen −26%), maar met
1 tot 3 trades zegt dat statistisch niets.

## Wat dit betekent voor het onderzoek

- **Hypothese A (blootstelling):** een signaal dat de positie verkleint in plaats van helemaal
  verkoopt (volatiliteitsdoel, 0-100%), houdt meer van de drift vast. Testbaar met de Alpha Research Engine.
- **Hypothese B (handelsfrequentie):** een minimale houdperiode en een hysteresisband op de filter
  halveren het aantal trades. Meetbaar via kosten per jaar.
- **Hypothese C (andere maatlat):** op een breed gespreide index is het doel misschien geen hoger
  rendement, maar een vergelijkbaar rendement met kleinere dalingen. De toets moet dan risico-gematcht
  zijn: koop-en-houd geschaald naar dezelfde beweeglijkheid.
- **Hypothese D (rotatie):** buiten de markt gaan levert 0% op. Rotatie naar geldmarkt (XEON) of
  obligaties (IEAG) verandert de rekensom.

Deze hypothesen staan in het hypothese-register van NEXUS Evolution en worden getest op een
afgesloten holdout-periode die tijdens het ontwikkelen niet bekeken wordt.
