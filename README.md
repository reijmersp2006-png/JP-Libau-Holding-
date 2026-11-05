# JP-libau Holding

All-in-one trading- en onderzoeksbot. Eén kern met vijf handelsafdelingen: **crypto,
memecoins, aandelen, goud/zilver en valuta**. Alles draait eerst met **nepgeld** (paper
trading). Live geld bestaat niet in deze versie en komt pas na de demofase en jouw
expliciete akkoord.

Winst is niet gegarandeerd. Het systeem is er om goedkoop en eerlijk vast te stellen
welke strategieën na kosten echt iets opleveren, en de rest uit te zetten.

Het volledige plan staat in [docs/PLAN.md](docs/PLAN.md).

## Status: fase 1, het fundament

| Onderdeel | Wat het doet |
| --- | --- |
| Data | Bitvavo (crypto, memecoins), Yahoo Finance (aandelen, goud, zilver, valuta), ECB (officiële wisselkoersen), DexScreener (memecoin-radar, alleen kijken) |
| Opslag | SQLite met het tijdstip van ophalen bij elke koers, zodat backtests niet in de toekomst kunnen kijken |
| Risico-afdeling | Mag elke order weigeren. Vaste grenzen die niemand (ook het leerlab niet) kan versoepelen |
| Boekhouding | Alles in euro, met omrekening van dollar, pond, yen en frank |
| Paper-broker | Vult tegen de laatste koers met fee en slippage per afdeling |
| Logboek | Elke beslissing met reden en alle risico-checks, in de database en per dag als JSONL |

Nog niet gebouwd: strategieën en backtest-lab (fase 2), 24/7 paper trading (fase 3),
het HQ-game-dashboard (fase 4) en de leerlus (fase 5).

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
jplh kill / unkill   # noodstop aan / uit
jplh resume          # pauze na een te grote daling opheffen
pytest               # alle tests
```

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
  collect.py   koersen verzamelen
  cli.py       opdrachtregel
```

Een afdeling geeft alleen een `Signal` af en ziet nooit geld of sleutels. Backtest, paper
en (later) live gebruiken dezelfde keten, zodat demo-resultaten ook echt iets zeggen.
