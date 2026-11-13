# APEX · Design-audit (D1)

> Milestone D, stap 1. Gemeten op de stand na Milestone C (PR #30, gemerged), vóór de wijzigingen van Milestone D.
> Werkwijze: 13 routes in een echte browser (Playwright/Chromium, 1440×900) tegen de API met de echte
> holding-data (dagcandles t/m 11-11-2026), plus code-inspectie van elk scherm.

## Gemeten basis

| Meting | Uitkomst |
|---|---|
| Routes getest | 13 (/, /hq, /news, /social, /radar, /crypto, /stocks, /forex, /meme, /evolution, /operations, /strategy-lab, /risk) |
| Consolefouten | 0 |
| Horizontale overloop (desktop) | 0 |
| Laadtijd tot netwerk stil | ongeveer 0,85 tot 1,7 s per route (lokaal, productie-build) |

De basis was technisch gezond. De problemen zaten in hiërarchie, gebruik van de data en eerlijkheid van lege schermen.

## Bevindingen per scherm

| Scherm | Probleem | Ernst | Opgelost in |
|---|---|---|---|
| Command Center | Geen duidelijke hoofdmaat: zes even zware kaarten. P&L-soorten (gerealiseerd, ongerealiseerd, paper, backtest, benchmark) liepen door elkaar. | hoog | D3 |
| Command Center | Onderzoekskansen en goedgekeurde trades stonden niet apart. Het was niet te zien wat op een besluit wacht. | hoog | D3 |
| /crypto, /stocks, /forex | Placeholders ("fase 2") terwijl er wél opgeslagen dag- en uurcandles zijn. | hoog | D4 |
| /meme | Kaarten "fase 2 nog niet", terwijl de DEX-radar al echte data toonde. Dat was verwarrend. | middel | D4 |
| AI HQ | Neural Core was een statisch organogram. Lijnen tussen rollen waren niet gebaseerd op echte overdrachten, en er was geen dossier per rol. | hoog | D5 |
| AI HQ | Copilot kende de vragen "welke providers zijn offline" en "wat onderzoeken de agents" niet. | middel | D7 |
| News Reactor | Bron-verificatie per bericht ontbrak (officieel tegenover media). | middel | D6 |
| Social Radar | Geen kopcijfers. Een ontbrekende X-verbinding stond klein in een kaart. | middel | D6 |
| Market Pulse | Er bestond geen pagina: alleen een kleine widget op het dashboard. | middel | D6 |
| Beslisketen | Alleen een compacte DecisionFlow op HQ. Er was geen stap-voor-stap-inspectie van één gebeurtenis. | hoog | D7 |
| Evolution Lab | De Arena toonde strategieën, maar niet visueel tegen koop-en-houd. Daardoor waren negatieve uitkomsten (IWDA) minder zichtbaar. | middel | D7 |
| Hele app | Grijs voor bijschriften (`slate-500` #6C7584) haalde 4,0:1 op een paneel, onder WCAG AA (4,5:1). `slate-600` haalde 2,3:1. | middel | D8 |
| Hele app | Panelen in grids misten `min-w-0`, waardoor brede tabellen de pagina op mobiel konden oprekken. | middel | D8 |
| Hele app | Links uit nieuwsfeeds werden ongecontroleerd klikbaar gemaakt (ook een eventuele `javascript:`-link). | hoog (beveiliging) | D8 |

## Wat goed was en bleef

* Het 4.1-ontwerp (Geist, donkere panelen, `Panel`, `StatusDot`, `TruthTag`, `DataBadge`) bleef de basis. Er is geen tweede systeem naast gezet.
* Elke cijferbron had al een label (LIVE, DELAYED, HISTORICAL, SIMULATED, UNAVAILABLE). Milestone D bouwt daarop voort.
* De noodstop, de Risk Guardian, live-uit, de admin-token en de audit-logging zijn niet aangeraakt.

## Screenshots

Voor-situatie: `before/desktop-*.png` (13 routes) in de projectmap
`/mnt/project-files/nexus-ai/research/milestone-d/`. Na-situatie: zie `APEX-VISUAL-QA.md`.
