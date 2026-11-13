# Multi-model evaluatie: opzet en stand (Milestone C)

## Doel

Meten of een taalmodel iets beter doet dan de vaste regels van NEXUS, en welk model, op dezelfde taken en
dezelfde data. Een model "wint" alleen als het 95%-interval (bootstrap over de items) van het verschil met de vaste
regels helemaal boven nul ligt.

## Twee datasets, met verschillende status

| Set | Bron van de labels | Doel | Status |
|---|---|---|---|
| `news-labels-v1` (30 koppen, bevroren) | de ontwikkelaar die ook de regels schreef | rooktest: werkt de meetopzet? | vaste regels 93%. **Te optimistisch** door dezelfde auteur; geen bewijs |
| `news-ceo-v1` (doorlopend) | een **onafhankelijke mens** (CEO of operator) op **echte** koppen uit de feeds | het echte oordeel | 0 labels; wacht op echte feeds |

Regels voor `news-ceo-v1`:

- Alleen echte, niet-gedupliceerde berichten. Fixtures worden geweigerd (getest).
- De labeler ziet alleen kop en bron, **niet** wat NEXUS ervan denkt.
- Vaste splitsing op basis van een hash van het bericht-id: `dev` mag bekeken en gebruikt worden om iets te
  verbeteren; **alleen `test` telt voor de eindscore**, en daarop wordt niets afgesteld.
- Een oordeel pas vanaf 50 testitems; daaronder meldt de arena "te weinig".
- Herlabelen overschrijft het eigen label (één label per persoon per bericht).

## Wat er gemeten wordt

| Maat | Hoe | Waar |
|---|---|---|
| Nauwkeurigheid en macro-F1 | per deelnemer op dezelfde items | `POST /api/ai/eval` (dataset kiezen) |
| Ongeldige antwoorden | antwoord buiten de labellijst of schemafout | arena |
| Kosten | werkelijke tokens × prijs; onbekende prijs = "onbekend" | arena, gateway |
| Latency | mediaan per deelnemer | arena |
| Betrouwbaarheid | foutpercentage per aanbieder en taak (30 dagen) | `/api/eval/status` |
| Kwaliteit van bewijs | aandeel beweringen met een geldige bronverwijzing, per auteur | `/api/eval/status` |
| Oplossen van meningsverschillen | aantal betwiste beweringen per debat | debatten |
| Kalibratie | Brier-score van afgerekende voorspellingen tegen 0,25 (altijd 50%) | arena, vanaf 30 voorspellingen |

## Stand op 13 november 2026

Geen enkel taalmodel is gemeten: er zijn geen sleutels. Er zijn geen afgerekende voorspellingen, dus kalibratie is
niet te meten. Er zijn geen echte debatten, dus de bewijskwaliteit is leeg. Dat staat ook zo in de UI ("niet
gemeten: geen sleutel"); er is geen score verzonnen.

## Volgende stappen

1. Echte feeds aan (omgeving "data-feeds") en dagelijks 10 tot 20 koppen labelen op /operations.
2. Bij 50 testitems: arena draaien met de vaste regels en elke ingestelde aanbieder.
3. Pas als een model aantoonbaar beter is én de kosten per correct label het waard zijn, gaat het
   `news_classification` naast de regels doen. De regels blijven altijd de terugval.
