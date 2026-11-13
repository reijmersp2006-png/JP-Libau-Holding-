# APEX · Trading Workstation (D4)

De placeholders `/crypto`, `/stocks` en `/forex` zijn vervangen door één onderzoeks-workstation. `/meme` gebruikt die ook.
**Er wordt vanuit dit scherm niets gehandeld.** Er is geen orderticket, live handelen staat uit, en elk voorstel
gaat langs de Risk Guardian en de CEO. De kop van elk scherm zegt dit: "Alleen onderzoek · geen orders vanuit dit scherm".

## Instrumenten (gemeten op 13-11-2026)

37 instrumenten met opgeslagen candles: 10 aandelen, 8 crypto, 5 memecoins, 4 valuta, 2 edelmetalen en 8 contextreeksen
(indices, rente, olie, dollarindex). 32 hebben dag- én uurcandles; 5 alleen dagcandles.

| Pagina | Klassen | Start |
|---|---|---|
| Crypto Workstation (`/crypto`) | crypto, meme | BTC-EUR |
| Equities Workstation (`/stocks`) | aandelen, metalen, context | IWDA.AS. De intro noemt het negatieve IWDA-onderzoek: de strategie verloor van koop-en-houd |
| Forex Workstation (`/forex`) | valuta, context | EURUSD=X |
| Meme Coin Research (`/meme`) | meme, met de DEX-radar eronder | DOGE-EUR |

Instrumenten buiten het handelsuniversum zijn gemarkeerd als "extra" (alleen onderzoek).

## Onderdelen

**Grafiek** (Lightweight Charts v5, `components/PriceChart.tsx`)
* Tijdschalen **alleen als er candles zijn**: 1 uur (ongeveer 5–14 dagen opgeslagen) en 1 dag. Een knop zonder data staat uit. Er is geen 1m/5m/1w: die data bestaat niet, dus de knop bestaat ook niet.
* Bereik 3M / 6M / 1J / 3J / Alles. Candles of lijn.
* Volume als histogram op een eigen schaal.
* SMA 20/50/200 en RSI 14 (Wilder) in een eigen paneel met lijnen op 70 en 30, aan en uit te zetten. De warm-up is leeg, niet geschat.
* Kruisdraad, zoom en pannen (standaard in Lightweight Charts).
* Vergelijken met een ander instrument in % vanaf het eerste gemeenschappelijke punt.
* Markeringen: amber "N" voor nieuws uit de database, violet "sim" voor gesimuleerde of fixture-gebeurtenissen.

**Versheid.** Elk scherm toont het label en de tijd van de laatste candle: "Vertraagd · 11 nov · 3 dagen geleden · geen streaming".
Is de candle ouder dan 4 dagen, dan staat er HISTORICAL. In de demo-omgeving wordt elk label SIMULATED. Nooit LIVE.

**Gemeten kenmerken** (vaste code, geen AI): rendement 1d/7d/30d/90d/1j/dit jaar, volatiliteit 20d en 1j (op jaarbasis,
met de juiste periodes per jaar voor 24/7-crypto en beursdagen), grootste daling in 1 jaar, 52-weeks bereik, volume
20d tegenover 1 jaar, ligging tegenover SMA 200 ("een beschrijving van het verleden, geen signaal") en RSI.

**Watchlist**: zoeken, categorieën, sorteren (naam, 1d, 30d) en "Mijn lijst" met ☆. Wordt bewaard in
`localStorage` onder `nexus.watchlist`, **alleen symbolen**: geen sleutels, tokens of persoonsgegevens.

**Onderzoekspaneel** (tabs)
* *Onderzoek*: AI-mening (apart gelabeld; leeg tot er een Council-run met verbonden aanbieder is), hypotheses en agenttaken over dit instrument. Bij memecoins ook de sociale meting en de veiligheidscontrole uit de Social Radar.
* *Nieuws*: berichten uit de database die dit instrument noemen, met fixture- en sim-label en een link naar het beslisspoor.
* *Risico*: limieten van de Risk Guardian (alleen lezen). De spreadregel kan hier niet worden gecontroleerd, omdat spread en orderboekdiepte ontbreken.
* *Data*: bron, wat beschikbaar is en wat ontbreekt met de reden.

## Wat ontbreekt per klasse (eerlijk getoond in het Data-tabblad)

| Klasse | Bron | Ontbreekt |
|---|---|---|
| Crypto | Bitvavo (publiek, EUR) | orderboek en spread, funding en open interest, on-chainstromen |
| Meme | Bitvavo + Social Radar | X-discussie (X API niet verbonden), concentratie van houders (GoPlus-host geblokkeerd in deze omgeving) |
| Aandelen | Yahoo (onofficieel, vertraagd) | jaarcijfers en winstkalender (bron nog niet gekozen, betaald), bedrijfsnieuws alleen via SEC/EDGAR |
| Metalen | Yahoo futures | termijnstructuur |
| Valuta | Yahoo + ECB | macrokalender en consensus, intraday-ticks |

## API (alleen lezen, geen token nodig, geen AI-kosten)

| Endpoint | Doel |
|---|---|
| `GET /api/workstation/universe` | alle instrumenten met klasse, tijdschalen, laatste koers, label |
| `GET /api/workstation/asset?symbol=&interval=1d\|1h&limit=` | candles, indicatoren, kenmerken, kwaliteit, nieuws, onderzoek (404 bij onbekend symbool, 422 bij een verkeerde tijdschaal) |
| `GET /api/market/overview` | Market Pulse: klassen, bewegers, correlatie (60 gemeenschappelijke dagen), regime |

Een POST op deze endpoints geeft 405 (getest). Code: `nexus/backend/nexus/workstation.py`, `apex_api.py`; tests: `tests/test_apex.py`.

## Gemeten prestaties (lokaal, productie-build, desktop)

| Meting | Waarde |
|---|---|
| Grafiek zichtbaar na navigatie | 1,3 s (inclusief API-aanroep en lazy chunk) |
| First contentful paint | 0,23 s |
| API `asset` (BTC-EUR, 750 dagcandles, 97 kB) | 32 ms |
| Wisselen van instrument | 0,19 s |
| Tijdschaal- of bereikwissel (klik tot volgende frame, inclusief Playwright-overhead) | 0,13 – 0,26 s |

## Bewust niet gebouwd

* Orderticket en uitvoering: live handelen staat uit, en orders lopen alleen via de bestaande gateway en de Risk Guardian.
* Tekengereedschap (trendlijnen): zonder opslag per gebruiker zou het verdwijnen bij herladen.
* Fundamentele cijfers: er is geen bron, dus er worden geen cijfers verzonnen.
