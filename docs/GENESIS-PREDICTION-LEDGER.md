# GENESIS · Prediction Ledger (E1.5, sectie 8)

Code: `nexus/backend/nexus/ledger.py`, tabellen in `db.py`, migratie `0006_genesis.py`. API: `GET /api/ledger`,
`POST /api/ledger/resolve` (onderzoekstoken), `POST /api/ledger/{pid}/amend` (alleen admin). Scherm: `/research#ledger`.

## Velden (alle velden uit de opdracht)

| Veld | Kolom |
|---|---|
| id | `pid` (`pred-…`) |
| agent, model, promptversie | `agent`, `provider`, `model`, `prompt_version` |
| instrument | `subject` |
| tijdstip | `created_at` (servertijd, nooit door de aanroeper te kiezen) |
| horizon | `horizon_end` (standaard 28 dagen) |
| uitkomstdefinitie | `outcome_def`: type `price_above`, symbool, interval `1d`, drempel, leesbare tekst |
| kans | `probability` (0–1) |
| bewijs | `evidence` (feit-ids) |
| marktdata op het moment van voorspellen | `market_snapshot` (slotkoers, peilmoment, label) en `data_asof` |
| evaluatiemoment, status, uitkomst | `PredictionOutcome`: `evaluated_at`, `evaluator`, uitkomst 0/1, `detail` (gebruikte candle); status open / due / resolved |
| koppeling | `workflow_trace` naar de onderzoeksopdracht |

## Onveranderbaar

- **ORM**: elke update of delete op `Prediction`, `PredictionAmendment` en `PredictionOutcome` geeft een `PermissionError`.
- **Database**: triggers in SQLite én PostgreSQL weigeren UPDATE en DELETE (ook buiten de applicatie om).
- **Hash-keten**: elke voorspelling bevat de hash van de vorige; `verify()` controleert de hele keten
  (`chain: intact` in het scherm).
- **Correcties** zijn amendementen met reden en actor, alleen **vóór** de horizon, alleen door de CEO (admin). De
  oorspronkelijke voorspelling blijft staan.

Geweigerd bij registratie (getest): kans buiten 0–1, horizon in het verleden, data van na nu, onbekend uitkomsttype,
niet-numerieke drempel. Dat maakt **voorspellingen achteraf onmogelijk**.

## Afrekenen

Vaste code (`resolve_due`): de eerste dagcandle op of na de horizon, slot > drempel = 1, anders 0. Geen mens en geen
model beslist de uitkomst.

## Scores

Per agent: Brier, log loss, richting met Wilson-95%-interval, Brier-skill tegen de klimatologische basislijn, en
kalibratiebakken **pas vanaf n ≥ 30**. Onder die grens zegt het scherm dat er nog geen uitspraak is.

## Holdout

De beschermde holdout (vanaf 12-11-2026) wordt niet aangeraakt. Uitkomsten in de ledger dienen alleen om agents te
scoren, **nooit** om strategieën te kiezen of bij te stellen. De quant-feiten waarop voorspellingen leunen gebruiken alleen
data van vóór de holdout.

## Stand

| | Gate 1 | Gate 2 | Gate 3 |
|---|---|---|---|
| Ledger | TESTED (append-only ORM + trigger, hash, amendement, afrekenen, scores) | CONNECTED: registreert basislijn-voorspellingen bij elke opdracht | nog geen afgerekende voorspellingen; eerste horizon over 28 dagen |
| AI-voorspellingen | TESTED | BLOCKED (geen aanbieder) | — |
