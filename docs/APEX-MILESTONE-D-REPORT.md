# APEX · Milestone D-rapport

**Institutional Design Excellence & Professional Trading Workstations.** D1 t/m D8 zijn afgerond. Er is niets
gemerged of uitgerold. Live handelen staat uit. Er is niets gekocht. De holdout is niet aangeraakt. Milestone E is niet begonnen.

## Per stap

| Stap | Resultaat | Goed / niet goed |
|---|---|---|
| D1 Audit | 13 routes gemeten (0 fouten, 0 overloop) plus 14 bevindingen. Zie `APEX-DESIGN-AUDIT.md` | goed |
| D2 Design system | tokens, typografie, `ds.tsx` (10 componenten plus grafiekkleuren), grafiek- en tabelstijl, toestanden, beweging. Zie `APEX-DESIGN-SYSTEM.md` | goed |
| D3 Command Center 6.0 | hoofdmaat plus een strip met 8 cijfers; gerealiseerd, ongerealiseerd, paper, backtest en benchmark apart; versheid zichtbaar; "wacht op jou"; markt, onderzoekskansen en goedgekeurde trades apart | goed |
| D4 Trading Workstation | `/crypto`, `/stocks`, `/forex` en `/meme` op echte opgeslagen candles. Zie `APEX-TRADING-WORKSTATION.md` | goed; geen orderticket (bewust) |
| D5 AI HQ 2.0 | Neural Core als netwerk met echte overdrachten, een dossier per rol en een lijst als alternatief | goed; weinig activiteit, omdat er nog weinig taken zijn |
| D6 News, Social, Pulse | bronverificatie per bericht; Social Radar met kopcijfers en eerlijke X-status; nieuwe Global Market Pulse (heatmap, correlatie, bewegers, regime) | goed; sociaal blijft leeg zonder X |
| D7 Evolution, Arena, Decision Theater, Copilot | Arena tegen koop-en-houd (IWDA rood en negatief); Decision Theater met 9 stappen; Copilot beantwoordt de 7 vragen met bewijslinks en vervolgacties | goed |
| D8 QA | 38 screenshots (3 viewports), 0 fouten, 0 overloop; contrast naar AA; prestaties gemeten; CI-rooktest. Zie `APEX-VISUAL-QA.md` | goed; geen schermlezertest |

## Nieuwe en hergebruikte onderdelen

**Nieuw (backend):** `workstation.py` (universum, asset, indicatoren, overzicht, agentdossier, overdrachten),
`apex_api.py` (5 GET-endpoints, alleen lezen), uitbreiding van de Copilot-onderwerpen (providers, agents, aandacht),
`tests/test_apex.py` (8 tests).

**Nieuw (web):** `ds.tsx`, `PriceChart.tsx`, `Workstation.tsx`, `NeuralGraph.tsx`, `/decisions`, `/pulse`,
`lib/url.ts`, `e2e/visual-smoke.mjs`.

**Hergebruikt:** `Panel`, `StatusDot`, `TruthTag`, `DataBadge`, `Empty`, `Skeleton`, `Segmented`, `useApi`, `useAdmin`,
`KillSwitch`, `EquityChart` (nieuwe stijl), de Organisatie-API, event-workflows, de Risk Guardian-API en de Social Radar-API.

## Belangrijke besluiten

1. **Geen nieuwe pakketten.** Lightweight Charts stond er al; SVG volstond voor heatmap, correlatie en netwerk. Zie `APEX-DESIGN-TOOL-EVALUATION.md`.
2. **Alleen bestaande tijdschalen.** 1 uur en 1 dag; geen 1m, 5m of 1w, omdat daar geen data voor is.
3. **AI-mening apart.** In de workstation staat AI-analyse in een eigen, gelabeld blok. Dat blok is leeg tot er een echte Council-run is.
4. **Wacht op jou** telt alleen geëscaleerde taken. Voorstellen hebben geen status "wacht" (`approved_by_guardian` of `vetoed`).
5. **Overdrachten** tellen alleen stappen die echt liepen. Overgeslagen, niet-toepasselijke en onbeschikbare stappen tellen niet.

## Copilot: de zeven vragen

| Vraag | Onderwerp | Bewijs en vervolg |
|---|---|---|
| Wat onderzoeken de AI-agenten? | agents | open taken, laatste sporen (link naar het Decision Theater), open hypotheses |
| Welke gebeurtenissen vragen mijn aandacht? | approvals | geëscaleerde taken (of: "er wacht niets"), link naar de takenwachtrij |
| Waarom is dit voorstel afgewezen? | rejection | voorstel met het oordeel van de Risk Guardian, Council-besluit en vastgelegde afwijzingen; zonder record een expliciet datagat |
| Wat zijn onze grootste risico's? | risk | waardering van het paper-account, aantal veto's in 7 dagen, live uit |
| Welke strategieën presteerden het best? | opportunities | Arena-uitdagers met walk-forward-Sharpe en poorten, laatste ontdekkingsrun |
| Welke providers zijn offline? | providers | elke niet-verbonden aanbieder met de reden |
| Wat hebben we deze week geleerd? | learning | getoetste hypotheses en het aantal afgerekende besluiten deze week |

Getest in Engels en Nederlands (`test_copilot_routes_the_founder_questions`).

## Tests

* Backend: **182 geslaagd** (`pytest`), waarvan 8 nieuw in `test_apex.py`.
* Web: `eslint` schoon, `tsc` schoon, `next build` met 26 statische routes.
* Browser: 38 screenshots zonder consolefouten of overloop. `e2e/visual-smoke.mjs` lokaal geslaagd.

## Beveiliging

| Bevinding | Ernst | Status |
|---|---|---|
| Links uit nieuwsfeeds werden zonder controle klikbaar (ook `javascript:`) | hoog | **opgelost**: `safeUrl()` laat alleen http(s) door, op alle 6 bronlinks (5 bestanden); `rel="noreferrer noopener"` |
| Demo-data kreeg in de workstation het label DELAYED in plaats van SIMULATED | middel (eerlijkheid) | **opgelost**: in de demo-omgeving wordt elk versheidslabel SIMULATED (getest) |
| Nieuwe endpoints zonder token | laag | bewust: alleen GET met marktdata en organisatiestatus, net als de bestaande GET-endpoints. Geen sleutels, geen kosten. POST geeft 405 |
| Watchlist in `localStorage` | laag | alleen symbolen; geen sleutels of tokens in de browser |
| Nieuws en sociale tekst | — | blijft onvertrouwd: getoond als tekst, nooit als HTML; React escapet |

Niet aangeraakt: Risk Guardian, trading gateway, noodstop, audit-logging, holdout-governance, API-budgetten,
CEO-goedkeuring, operatorrechten en authenticatie.

## Niet verbonden (eerlijk getoond)

X API, betaalde aandelenbron (jaarcijfers en winstkalender), orderboek en spread, funding en open interest,
on-chainstromen, macrokalender en consensus, en de GoPlus-host (geblokkeerd in deze omgeving). AI-aanbieders zonder sleutel
staan in Operations als niet verbonden. Elk scherm toont "wat ontbreekt" in plaats van nullen.

## Beperkingen

* Koersen zijn vertraagd (laatste dagcandle 11-11-2026) en er is geen streaming. Uurcandles beslaan maar 5–14 dagen.
* Neural Core en Decision Theater tonen nu één gesimuleerd fixture-spoor. Ze worden pas rijk met echte gebeurtenissen.
* Geen schermlezer- of axe-test; geen pixel-regressie (zie de QA).
* Interactietijden zijn gemeten met Playwright-overhead; echte gebruikerslatentie ligt lager.

## Resterend werk (voorstel, niet gestart)

1. axe-scan in de CI-rooktest en een handmatige schermlezer-ronde.
2. Bevroren fixture-API, daarna pixel-regressie met een drempel van ongeveer 0,1%.
3. Command-palette (⌘K) met shadcn/ui zodra er meer schermen zijn.
4. Bronkeuze voor aandelen (betaald) is een CEO-besluit.
