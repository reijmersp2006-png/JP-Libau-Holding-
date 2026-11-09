# JP-libau Holding

All-in-one trading- en onderzoeksbot. Eén kern met vijf handelsafdelingen: **crypto,
memecoins, aandelen, goud/zilver en valuta**. Alles draait eerst met **nepgeld** (paper
trading). Live geld bestaat niet in deze versie en komt pas na de demofase en jouw
expliciete akkoord.

Winst is niet gegarandeerd. Het systeem is er om goedkoop en eerlijk vast te stellen
welke strategieën na kosten echt iets opleveren, en de rest uit te zetten.

Het volledige plan staat in [docs/PLAN.md](docs/PLAN.md).

## Status: fase 1 tot en met 4

| Onderdeel | Wat het doet |
| --- | --- |
| Data | Bitvavo (crypto, memecoins), Yahoo Finance (aandelen, goud, zilver, valuta), ECB (officiële wisselkoersen), DexScreener (memecoin-radar, alleen kijken) |
| Opslag | SQLite met het tijdstip van ophalen bij elke koers, zodat backtests niet in de toekomst kunnen kijken |
| Risico-afdeling | Mag elke order weigeren. Vaste grenzen die niemand (ook het leerlab niet) kan versoepelen |
| Boekhouding | Alles in euro, met omrekening van dollar, pond, yen en frank |
| Paper-broker | Vult tegen de laatste koers met fee en slippage per afdeling |
| Logboek | Elke beslissing met reden en alle risico-checks, in de database en per dag als JSONL |

| Strategieën | Trend (gemiddelden), momentum, uitbraak en terugkeer naar het gemiddelde, met koop-en-houd als maatlat |
| Backtest-lab | Walk-forward: instellingen kiezen op oude data, testen op nieuwe. Handelt pas op de volgende opening, met dezelfde kosten als paper |

| Afdelingen | Elke afdeling heeft een eigen potje nepgeld (crypto €300, memecoins €50, aandelen €350, goud/zilver €150, valuta €150), eigen boekhouding en logboek |
| Leerlus | Elke week kiest elke afdeling per instrument de strategie die de laatste 500 dagen het best werkte voor risico, na kosten. Koop-en-houd doet mee en wint als niets duidelijk beter is |
| 24/7 paper | GitHub Actions draait elk uur een ronde (`.github/workflows/paper.yml`). De stand staat op de branch `paper-data` |
| HQ-dashboard | Een eiland in game-stijl met een gebouw per afdeling, levensbalk (risicoruimte), dagbudget, levels, missies en een logboek. Staat op GitHub Pages |

Nog niet gebouwd: het wekelijkse leerrapport en nabesprekingen per trade (fase 5).

## Kern + jacht, en de spelregel

Op ~2,5 jaar echte koersen verloor actief handelen na kosten van gewoon vasthouden bij aandelen, goud/zilver en valuta. Daarom werkt elke afdeling nu zo (`[desk_mode]` in de config):

| Afdeling | Werkwijze |
|---|---|
| Crypto | **kern + noodrem**: vasthouden, eruit als bitcoin meer dan 5% onder zijn 200-dagengemiddelde zakt, weer erin als hij er 5% boven staat (de marge voorkomt heen-en-weer: kosten €71 → €19 in de test) |
| Memecoins | **jacht**: weekkeuze van strategieën, alleen wisselen als een nieuwe duidelijk beter is, niet kopen bij slecht marktweer |
| Aandelen, goud/zilver, valuta | **kern**: vasthouden, elk kwartaal terug naar gelijke delen |
| De holding | elk kwartaal het geld tussen de afdelingen terug naar de vaste verdeling (`[desks]`), als een afdeling meer dan 10% afwijkt |

**Spelregel**: een aanpassing gaat pas live als ze in `jplh backtest --desks` op echte koersen minstens zo goed is als wat er draait. De CI draait die toets bij elke pull request, en het rapport laat per afdeling zien of de live-werkwijze "in orde" is.

De toets draait op zoveel geschiedenis als er is (Bitvavo en Yahoo tot ruim tien jaar terug) en test ook rotatie op momentum, een marge rond het 200-dagengemiddelde (minder heen-en-weer, dus minder kosten) en drie manieren om het geld tussen de afdelingen te verdelen.

## Het dashboard openen

- **Online**: `https://reijmersp2006-png.github.io/JP-Libau-Holding-/` (eenmalig aanzetten: Settings,
  Pages, bij Source kies je "GitHub Actions").
- **Lokaal met nep-data**: `jplh dashboard --demo` opent het in je browser.

## Risicogrenzen

| Regel | Grens |
| --- | --- |
| Maximale daling vanaf de top | 15%, daarna pauze tot jij `jplh resume` doet |
| Dagverlies | 3%, daarna geen nieuwe aankopen die dag |
| Per instrument | max 25% van het vermogen |
| Per afdeling | crypto 40%, memecoins 5%, aandelen 50%, goud/zilver 30%, valuta 20% |
| Totaal belegd | max 90%, altijd 10% cash |
| Trades per dag | max 10 |
| Koers ouder dan 3 uur | niet handelen (ook als de wisselkoers oud is) |
| Bijkopen bij verlies | nooit |
| Noodstop (`jplh kill`) | blokkeert elke order, ook verkopen |

In `config/holding.toml` kun je grenzen alleen **strenger** maken. Een ruimere waarde
wordt geweigerd.

## Gebruiken

Python 3.11 of nieuwer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

jplh doctor          # zijn alle databronnen bereikbaar?
jplh selftest        # hele keten testen met nep-koersen
jplh collect         # nieuwste koersen ophalen voor alle afdelingen
jplh collect --demo  # nep-koersen, zonder internet
jplh status          # vermogen, posities, laatste gebeurtenissen
jplh collect --interval 1d --limit 1440   # dagkoersen van jaren terug
jplh backtest        # walk-forward-backtest, rapport in reports/
jplh backtest --demo # zelfde, met nep-koersen
jplh run             # één paper-ronde voor alle afdelingen + dashboard bijwerken
jplh dashboard       # dashboard openen (met --demo: nep-wereld)
jplh kill / unkill   # noodstop aan / uit
jplh resume          # pauze na een te grote daling opheffen
jplh jarvis          # Telegram-berichten van Phil beantwoorden en alarmen nalopen
pytest               # alle tests
```

Jarvis op Telegram (elke 10 minuten): `/stand`, `/briefing`, `/waarom BTC`,
`/alarm BTC 80000` (seintje bij die koers, koopt of verkoopt nooit iets), `/alarmen`,
`/alarm weg BTC`, `/noodstop` en `/hervat`. Elke zondagavond stuurt Jarvis een weekrapport.

Schaduw-arena: per afdeling draaien 8 andere strategieën op papier mee, met hetzelfde geld en
dezelfde echte koersen, vanaf de eerste paper-dag (alleen vooruit kijken). Wint een uitdager
90 dagen op rendement én Sharpe, dan meldt Jarvis dat. Promoveren beslist alleen Phil, en
alleen als hij ook `jplh backtest --desks` wint. Te zien in het Onderzoekslab.

Wat als?: kies op het dashboard een bedrag, een afdeling en een instapdatum en zie wat de
huidige regels op echte koersen hadden opgeleverd naast gewoon vasthouden. Hiervoor haalt de
uurronde één keer per dag 1500 dagkoersen op.

Je hoeft dit niet op je eigen computer te draaien: vanaf fase 3 draait de bot in de
cloud via GitHub Actions. Bij elke pull request controleert GitHub al automatisch of de
tests slagen en of de databronnen bereikbaar zijn.

## Opbouw

```
src/jplh/
  data/        bitvavo, yahoo, ecb, dexscreener, demo
  config.py    instellingen + vaste risicogrenzen (default_config.toml)
  store.py     SQLite-opslag
  prices.py    alles omrekenen naar euro
  risk.py      risico-afdeling met vetorecht
  broker.py    paper-broker
  ledger.py    boekhouding
  journal.py   logboek
  holding.py   de keten: signaal -> risico -> broker -> boekhouding -> logboek
  strategies.py  strategieën (alleen signalen, kunnen niet in de toekomst kijken)
  backtest.py  backtest-motor en walk-forward
  report.py    backtest-rapport per afdeling
  desks.py     de vijf afdelingen, elk met eigen potje en weekkeuze van strategieën
  paper.py     één paper-ronde voor de hele holding, en de demo-wereld
  site.py      stand voor het dashboard (state.json)
  hq/          het game-dashboard (één HTML-bestand)
  collect.py   koersen verzamelen
  cli.py       opdrachtregel
```

Een afdeling geeft alleen een `Signal` af en ziet nooit geld of sleutels. Backtest, paper
en (later) live gebruiken dezelfde keten, zodat demo-resultaten ook echt iets zeggen.
