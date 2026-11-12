# NEXUS 4.0 "Project Sentinel" + design 4.1 · stand van zaken (12 november 2026)

Labels: **GEÏMPLEMENTEERD** (code staat er), **GETEST** (automatische tests slagen), **VERBONDEN** (praat met een echte bron),
**GESIMULEERD** (paper of backtest), **NOG NIET BESCHIKBAAR** (ontbreekt een sleutel, bron of deploy).
Geslaagde unit-tests betekenen niet dat iets productierijp is.

## 1. Wat er gebouwd is

| Onderdeel | Status | Toelichting |
|---|---|---|
| Holdout-governance (manifest, registratie vóór evaluatie, één blik per kandidaat, besmettingsregister, prospectieve periode) | GEÏMPLEMENTEERD · GETEST (6 tests) | Alle dagdata t/m 11-11-2026 is als besmet gemarkeerd, omdat het lab en de IWDA-audit die al zagen. Een nieuwe holdout begint op 12-11-2026 en heeft minstens 63 handelsdagen nodig. Tot dan blijft gate 3 "pending" en kan geen enkele challenger kampioen worden. |
| NEXUS Central (19 rollen, 6 afdelingen, takenmachine met vaste overgangen, escalatie naar CEO, dedupe, AI-limiet 3 per dag) | GEÏMPLEMENTEERD · GETEST | Er zijn geen vrije agent-lussen, alleen vaste taaksoorten met vaste stappen. Agents kunnen geen limieten, regels, brokerrechten of geschiedenis veranderen. |
| Executive briefing (dagelijks, met lijst "ontbreekt") | GEÏMPLEMENTEERD · GETEST | Draait als dagelijkse job. |
| Live Decision Timeline (9 stappen per Council-run of voorstel) | GEÏMPLEMENTEERD · GETEST | Leeg zolang er geen Council-run of voorstel is geweest. |
| News Reactor (12 stappen, ontdubbelen, feiten tegenover speculatie, relevantie, gemeten latency, event study) | GEÏMPLEMENTEERD · GETEST · NOG NIET VERBONDEN | 9 officiële bronnen (Fed, ECB, BLS, SEC, EDGAR, Kraken- en Coinbase-status). In deze sandbox blokkeert de proxy de feeds, dus er zijn 0 echte berichten en geen gemeten latency. |
| X Intelligence + Meme Radar (momentum, botrisico, basislijn, lead/lag, betrouwbaarheid van influencers) | GEÏMPLEMENTEERD · GETEST · NOG NIET BESCHIKBAAR | Gebruikt alleen de officiële X API v2. Er is geen `X_BEARER_TOKEN`, dus geen metingen. |
| On-chain veiligheidscheck (GoPlus + DexScreener, 8 verplichte checks) | GEÏMPLEMENTEERD · GETEST · NOG NIET VERBONDEN | Ontbrekende data telt als "niet geslaagd". Een meme-koopvoorstel zonder recente geslaagde check krijgt een veto van de Risk Guardian. |
| CEO Copilot (8 onderwerpen, bewijsverwijzingen, kan niets uitvoeren) | GEÏMPLEMENTEERD · GETEST | Zonder Anthropic-sleutel antwoordt hij deterministisch uit de database. Met een sleutel formuleert Claude het antwoord; verzonnen verwijzingen worden geweigerd. |
| Market Pulse | VERBONDEN (vertraagd) | Gebruikt echte dagkoersen uit de holding-database, laatste slot 11-11-2026. Dit is geen streaming. |
| Design 4.1: Command Center, AI Headquarters, News Reactor, Social Radar, restyle van het Evolution Lab | GEÏMPLEMENTEERD | Lint, typecheck en productie-build slagen; de schermen draaien zonder console-fouten. |
| Live handelen | UIT | Er is geen hefboom of derivaten, en agents gaan altijd via de gateway en de Risk Guardian. |

## 2. UI-audit (vóór 4.1)

Gevonden in de oude UI:
- neon-gloed op het logo en de panelen
- gradiënt-randen
- vijf felle labelbadges bovenaan het Command Center
- veel kleine kaartjes
- overal hoofdletter-eyebrows
- verzadigd cyaan
- verouderde tekst ("geen enkele rol draait op een taalmodel")

Wat er veranderd is:
- **Palet:** bijna-zwart en grafiet, ijsblauw als accent, haarlijnen in plaats van randen.
- **Herkomstlabels:** een punt met een woord in plaats van een badge.
- **Command Center:** één KPI-rij en een grote curve van 360 px.
- **Nieuwe onderdelen:** Neural Core (echte activiteit), Decision Flow en Market Pulse.
- **Toegankelijkheid:** skip-link, focusrand, `prefers-reduced-motion` en aria-labels.

## 3. Prestaties (lokaal, SQLite, echte paper-data)

| Endpoint | Tijd | Grootte |
|---|---|---|
| /api/command-center | 86 ms | 35 kB |
| /api/pulse | 66 ms | 17 kB |
| /api/social/radar | 73 ms | 1,4 kB |
| /api/central/org, /timeline, /briefing, /api/news/reactor | 1 tot 4 ms | < 7 kB |

De JS-chunks zijn samen 1,1 MB (ongecomprimeerd). De pagina's worden statisch voorgebouwd en de data komt per endpoint binnen met een verversing van 30 s tot 2 min.

## 4. Onderzoeksbevindingen (ongewijzigd sinds 3.1, nu eerlijk gelabeld)

- Er is geen strategie die koop-en-houd op IWDA verslaat. De arena-kampioen haalt Sharpe 0,50 tegen 1,27 voor koop-en-houd.
- De holdout is besmet. Elke eerdere "out-of-sample"-claim op dagdata telt daarom niet meer, en een nieuwe meting vraagt om nieuwe data.
- Er bestaat nog geen meetbare leerlus voor nieuws of sociaal: daar zijn nul echte gebeurtenissen voor.

## 5. Wat nog ontbreekt (afhankelijkheden)

1. **`ANTHROPIC_API_KEY`** op de server. Daarmee gaan de Council-runs en de Claude-formulering van de Copilot echt draaien.
2. **Deploy met open netwerk**, of een proxy die de nieuwsfeeds, GoPlus en DexScreener toestaat.
3. **`X_BEARER_TOKEN`**: een eigen X API-abonnement, voor de sociale metingen.
4. **Tijd:** ongeveer 63 handelsdagen nieuwe data voor een schone holdout, en minstens 8 nieuwsgebeurtenissen per categorie voor de event study.

## 6. Volgende mijlpaal

- Na de deploy met sleutels draait elke job één week.
- Daarna volgt de eerste echte meting van nieuwslatency, Council-kalibratie en de sociale basislijn.
- De Grok-vergelijking wordt uitgebreid met equity-curves en het onderscheid tussen gerealiseerd, paper en backtest.
- De SaaS-onderdelen (multi-tenant, facturatie) blijven uit tot er een juridische toets is geweest.
