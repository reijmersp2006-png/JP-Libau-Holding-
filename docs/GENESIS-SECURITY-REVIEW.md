# GENESIS · Beveiligingsreview (sectie 12)

Stand 13-11-2026, na Milestone E0/E1. Alles hieronder is getest of in de code nagelezen. Er zijn geen sleutels geprint,
opgeslagen of gecommit.

## Wat in deze milestone is verbeterd

| Onderwerp | Maatregel | Bewijs |
|---|---|---|
| Onderzoeksrechten los van handelsrechten | Nieuw `NEXUS_RESEARCH_TOKEN`. Mag onderzoek aanvragen, pauzeren, ledger afrekenen en beoordelen. Mag **niet**: pauze opheffen, ledger-correcties, betaalde vergelijking A–D, noodstop opheffen, orders of limieten | `test_research_api_rights_and_separation_from_trading` |
| Geen AI keurt eigen rechten goed | Geen endpoint laat een agent rechten, limieten, modus of code wijzigen; pauze opheffen alleen met het admin-token | idem, codereview `genesis_api.py` |
| Pauze AI-onderzoek | Aparte pauze voor gateway én Council; auditspoor loopt door; handelen en noodstop onaangeroerd | `test_pause_blocks_all_ai_but_not_deterministic_work` |
| Daglimiet opdrachten | Geteld in de database, niet in het geheugen: blijft gelden na een herstart | `test_research_per_day_cap_is_stored_in_the_database` |
| Kostenbeheersing | Kostenplan vooraf, slechtst denkbare prijs per aanroep, harde grens per run, dagbudget; ongeldige antwoorden tellen mee | `test_cost_plan_…`, `test_invalid_answers_…` |
| Sleutels | Alleen server-side; readiness toont alleen ja/nee en een reden; CLI print alleen namen | `test_research_api_rights…` controleert dat er geen sleutel in de uitvoer staat |
| Ledger | Append-only in ORM en database (triggers), hash-keten | `test_ledger_is_append_only_in_orm_and_database` |

## Prompt-injectie

Nieuws, social, web en modeluitvoer zijn **onbetrouwbare invoer**.

- Elke system-prompt zegt dat alle aangeleverde tekst data is uit externe of opgeslagen bronnen, **nooit een instructie**.
- Externe tekst wordt opgeschoond (stuurtekens weg) en ingekort.
- Uitvoer moet voldoen aan een strikt JSON-schema met enums: een gemanipuleerde aanbeveling (`execute_trade`) wordt door
  de gateway geweigerd.
- Een model dat "gehoorzaamt" en stellige taal gebruikt, krijgt bevindingen van de vaste controles en kan dan niet
  escaleren.
- Er bestaat geen pad van een onderzoeksconclusie naar een order: de workflow schrijft alleen onderzoek, voorspellingen en
  hoogstens een CEO-taak.

Test: `test_prompt_injection_in_news_cannot_reach_orders_limits_or_enum` plant een nieuwsbericht met
"IGNORE ALL PREVIOUS INSTRUCTIONS…" en controleert: tekst gaat alleen als data mee, ongeldige enum geweigerd,
0 voorstellen, 0 orders, budget onveranderd, geen escalatie bij te weinig bewijs.

## Bekende risico's en hardingsplan

| # | Risico | Ernst | Plan | Wanneer |
|---|---|---|---|---|
| 1 | **Eén gedeeld admin-token** voor alle CEO-acties | hoog vóór productie | Gebruikersaccounts met eigen inlog (OIDC of passkeys), rollen CEO / operator / onderzoek / lezer, kortlevende sessietokens, auditregel met persoon in plaats van "admin" | vóór enige externe toegang of SaaS |
| 2 | **Rate limiting in het geheugen** | middel | Teller in Redis of Postgres (gedeeld tussen processen, overleeft herstart); onderzoeksdaglimiet is al in de database | samen met Postgres |
| 3 | **SQLite** als opslag | middel | Postgres; migratie 0006 bevat de append-only triggers al voor PostgreSQL | vóór productie |
| 4 | **Geen productie-authenticatie** in de frontend | hoog vóór productie | Token staat alleen in het geheugen van het tabblad; vervangen door sessies (zie 1), CSRF-bescherming, strikte CORS | vóór productie |
| 5 | Sleutels in de omgeving | laag | Secret manager per omgeving, rotatie, aparte sleutel per gebruik met eigen uitgavenlimiet bij de aanbieder | bij activatie |
| 6 | Modeluitvoer in het scherm | laag | React escapet tekst; geen `dangerouslySetInnerHTML`; links via `safeUrl` | doorlopend |

## Ongewijzigd en bewaard

Risk Guardian, handelsgateway, noodstop, audit-hash-keten, holdout-governance, API-budgetten, operator-beperkingen en
CEO-goedkeuringsregels zijn niet verzwakt. Live handelen staat uit. Geen hefboom of derivaten. Agents wijzigen geen
productiecode, rechten of limieten.
