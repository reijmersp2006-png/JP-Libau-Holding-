# Master Prompt 9.0: Project Overmind

*Eén Command Center voor JP-Libau Holding. NEXUS is de onderzoekslaag eronder. De bot en het risicobeheer zijn niet veranderd.*

- **Datum:** 23 november 2026
- **Branch:** `claude/project-thread-ektafa`, vanaf `main` @ `71812e5` (merge #33)
- **Statuswoorden:**
  - IMPLEMENTED: de code bestaat.
  - TESTED: er zijn tests en die slagen.
  - CONNECTED: de onderdelen praten met elkaar.
  - DEPLOYED: het staat ergens online.
  - OPERATIONAL: het draait echt, met bewijs uit de runtime.
  - SIMULATED: de data is nep.
  - BLOCKED: het kan niet draaien door een ontbrekende sleutel, host of akkoord.
  - VALIDATED: het is aantoonbaar nuttig.

## In het kort

- **Hoofdscherm.** `index.html` is nu het **JP-Libau Holding Command Center**. Het heeft vijf secties: Overview, Trading, NEXUS Intelligence, Academy en CEO Control. De pixelstad leeft door als `stad.html`. Factsheet en Brein blijven bestaan.
- **Vijf nieuwe onderdelen**, allemaal gevoed door echte data uit de bot:
  - Intelligence Graph
  - Onderzoeksradar
  - Decision Replay
  - System Pulse
  - Risk Simulator
- **Leest alleen.** Er is geen enkele knop die iets verandert.
- **Nieuw contract `jplh.overmind/v1`** (`overmind.json`): attention, decisions, changes, pulse, replay, exposure, scenarios, radar en graph. De bot maakt het bij elke ronde. Gaat dat mis, dan loopt de ronde gewoon door en meldt het dashboard dat eerlijk.
- **Jarvis** antwoordt met vaste code op `/aandacht`, `/veranderd`, `/systeem` en `/pauze crypto`. De bestaande commando's zijn ongewijzigd.
- **Tests:**
  - jplh: 154 passed (11 nieuw).
  - NEXUS: 215 passed.
  - Browser (desktop en mobiel): 0 consolefouten, 0 horizontale overloop, 0 axe-schendingen (WCAG 2 A/AA) op 13 schermen.
- **Niet gemerged en niet uitgerold.** Dat is een besluit van de CEO.

## 1. Verificatie (P0)

| Wat | Bevinding |
|---|---|
| PR #30, #31, #32 | gemerged op 13-11 |
| PR #33 (8.0) | gemerged op 23-11 16:25. Geen open PR's. |
| `docs/UNIFICATION-8.0.md` | aanwezig; de aanbevolen route A (statisch op Pages) is hier gevolgd |
| Productie | `paper.yml` 16:09 success (ronde en Pages-uitrol); `jarvis.yml` elke 10 minuten success |
| Afhankelijkheden | geen. Deze branch bouwt direct op `main`. |

## 2. Informatie-architectuur en data-eigendom

| Sectie | Beantwoordt | Data (eigenaar) |
|---|---|---|
| **Overview** | Wat gebeurt er? Wat veranderde? Wat vraagt aandacht? Presteert het? | `state.json` (bot), `overmind.json` (attention, decisions, changes, pulse) |
| **Trading** | Per afdeling: kapitaal, posities, belegd/cash, resultaat tegen vasthouden, daling tegen grens, kosten, instrumenten en strategie, recente beslissingen, risicoregels, Academie, coach, onderzoek | `state.json`, en `overmind.json` (replay, radar) |
| **NEXUS Intelligence** | Wat onderzoekt NEXUS? Radar, graph, onderzoeksrecords, markt en verkenners, NEXUS-onderdelen met hun echte status | `overmind.json`; records alleen als `intelligence/records.json` er is |
| **Academy** | Wat is geleerd, wat verworpen, wat nog onzeker? Live score, geschiedenis, arena, coaches, lessen | `state.json` (academy, coach, arena, lessons) |
| **CEO Control** | Besluiten, Jarvis, kosten, risico, System Pulse, Decision Replay, Risk Simulator, audit | `overmind.json` en de openbare GitHub-runs (Jarvis, publicatie) |

**Eén bron per gegeven.** De bot is eigenaar van alle getallen. `overmind.json` wordt afgeleid in vaste code en verzint niets. De browser rekent alleen de leeftijd van tijdstempels opnieuw uit en de simulator.

**Aandachtsvolgorde:**
1. Kritiek: noodstop, gepauzeerde afdeling, verouderde ronde of koersen, dicht bij de pauzegrens.
2. Besluiten die op de CEO wachten: hervatten, promotie, NEXUS-escalatie.
3. Veranderingen in 24 uur.
4. Context: tegen vasthouden, Academie.

## 3. Designsysteem Institutional 2.0

**Bestand:** de tokens staan in `src/jplh/hq/index.html` (`:root`).

**Kleur**
- Donker oppervlak `#0e1116`; tekst in drie niveaus; merkgoud `#c9a961` alleen voor identiteit en focus.
- Afdelingskleuren zijn de categorische slots 1–5, gecontroleerd met `validate_palette.js` op dit oppervlak: lichtheidsband, chroma, CVD (slechtste paar 8,4) en normaal zicht (19,3) zijn allemaal PASS.
- Status heeft vier vaste kleuren, altijd met icoon en label (● ▲ ■ ✕ ?). De rode statustekst is lichter gemaakt (`#f27b7b`) voor 4,5:1.

**Opbouw**
- Componenten: KPI-strip, aandachtskaart, statuspil, label (REAL, DETERMINISTIC, NOT RATED, …), meter met grenslijn, tabel, lege toestand en replay-lagen.
- Typografie: systeemfont, cijfers in mono met vaste breedte.

**Grafieken en beweging**
- Grafieken zijn SVG met dunne lijnen, een directe label, een hover-kruisdraad en een tooltip. Staven lopen vanaf nul.
- Er is één beweging: een korte flits bij een echte verandering, en geen beweging bij `prefers-reduced-motion`.
- Er is geen geanimeerde "AI-activiteit".

**APEX-componenten.** De NEXUS-componenten (React/Next) zijn niet letterlijk overgenomen, omdat dat een build-stap en een framework op Pages vraagt. Hun patronen zijn wel gevolgd: KPI-strip, Decision Theater-lagen, Market Pulse en statusvocabulaire.

## 4. Feature-voor-feature bewijs

| Functie | Status | Bewijs |
|---|---|---|
| Command Center, 5 secties en werkende navigatie (hash-routes, deelbare links) | IMPLEMENTED, TESTED | `test_demo_site_ships_command_center_city_and_export`; browsertest op 13 routes |
| Overview: aandacht, besluiten, veranderingen, KPI's, curve, afdelingen, hartslag | IMPLEMENTED, TESTED, CONNECTED (echte `paper-data`) | screenshots `desktop-overview.png` en `mobiel-overview.png` |
| Trading-werkruimtes (5) | IMPLEMENTED, TESTED, CONNECTED | `desktop-trading.png` |
| Onderzoeksradar | IMPLEMENTED, TESTED, CONNECTED | `test_radar_scores_are_transparent_or_not_rated`. Op de echte data is vandaag **0 van 60** vragen beoordeeld: te weinig bewijs, en dat is eerlijk. |
| Intelligence Graph (138 knopen en 202 relaties op de echte data, 12 relatietypes) | IMPLEMENTED, TESTED, CONNECTED | `test_graph_only_contains_typed_edges_between_known_nodes`; `desktop-graph-selected.png` |
| Decision Replay (drie gescheiden lagen) | IMPLEMENTED, TESTED, CONNECTED | `test_replay_never_uses_data_from_after_the_decision`; `desktop-replay.png` |
| System Pulse | IMPLEMENTED, TESTED, CONNECTED. Jarvis en de publicatie worden OPERATIONAL-bewijs zodra ze op Pages draaien, via de openbare GitHub-runs. | `test_pulse_turns_stale_without_new_rounds` |
| Risk Simulator (6 scenario's, schaal 0,5–2×, reset) | IMPLEMENTED, TESTED, CONNECTED | `test_simulator_inputs_match_the_portfolio`; browserklik |
| Jarvis `/aandacht`, `/veranderd`, `/systeem`, `/pauze` | IMPLEMENTED, TESTED | `test_jarvis_answers_are_grounded_and_change_nothing` |
| NEXUS-onderzoeksrecords | BLOCKED | NEXUS is niet uitgerold. Het scherm en Jarvis zeggen "niet verbonden". |
| AI-analyse, modelgebruik en kosten | BLOCKED | geen sleutel; het dashboard toont 0 aanroepen en €0 |
| Alles hierboven DEPLOYED of OPERATIONAL | nee | pas na merge; dan publiceert `paper.yml` het bij de volgende ronde |
| VALIDATED (aantoonbaar nuttig voor beslissingen) | nee | vraagt gebruik door de CEO (zie backlog, meetplan) |

## 5. Wat er technisch veranderde

| Bestand | Wat |
|---|---|
| `src/jplh/overmind.py` (nieuw) | `jplh.overmind/v1` en de Jarvis-teksten. Alleen lezen, vaste code. |
| `src/jplh/hq/index.html` (nieuw) | Het Command Center: één bestand, zonder framework en zonder externe aanvragen behalve de openbare GitHub-API op Pages |
| `src/jplh/hq/stad.html` | De oude `index.html` (de stad) onder een nieuwe naam, met een link terug |
| `src/jplh/site.py` | `write_site(..., overmind)` schrijft `overmind.json`. `build_overmind` vangt fouten af. |
| `src/jplh/paper.py`, `src/jplh/cli.py` | Geven de overmind-gegevens door aan `write_site`; alleen de dashboardregel |
| `src/jplh/commands.py` | 4 nieuwe Jarvis-commando's en de help-tekst |
| `tests/test_overmind.py` (nieuw), `tests/test_desks_site.py` | Nieuwe tests. De merktoets is nu hoofdletterongevoelig ("JP-Libau Holding"). |

**Niet aangeraakt:** strategieën, orderuitvoering, boekhouding, risicodrempels, pauzes, planning, workflows, live-modus en de holdout-gegevens.

## 6. Privacy en beveiliging

| # | Bevinding | Ernst | Status |
|---|---|---|---|
| P1 | `overmind.json` is opgebouwd uit een expliciete selectie velden. Getoetst: geen `chat`, token, secret, password of offset; geen Telegram-chat-id; geen lokale paden. | – | opgelost en getest |
| P2 | **De repository is openbaar, en de branch `paper-data` dus ook.** Daarin staan alle databases, de logboeken en het Telegram-chat-id (in `holding.sqlite3`, state `telegram`). Een chat-id alleen geeft geen toegang (daar is het bot-token voor nodig, en dat staat veilig als secret), maar het is wel persoonlijk. | middel | **CEO-besluit**, zie 9 |
| P3 | Het Pages-dashboard is openbaar: portefeuille en resultaten zijn voor iedereen met de URL te zien. Dat was al zo; 9.0 voegt geen nieuwe soort gegevens toe. | laag tot middel | CEO-besluit, zie 9 |
| P4 | Het dashboard heeft geen schrijvende acties. Getest: geen POST in de pagina. Noodstop, hervatten en promoties gaan alleen via Telegram (de geautoriseerde chat) of de eigenaar. | – | goed |
| P5 | De openbare GitHub-API wordt alleen aangeroepen vanaf `*.github.io`, zonder token. Bij een limiet of storing toont het dashboard ONBEKEND. | laag | goed |
| P6 | `build_overmind` kan de handelsronde niet laten mislukken (getest met kapotte invoer). | – | goed |

**Aanbeveling voor een privé CEO-werkplek.** De bedragen zijn indicatief; controleer de actuele prijzen vóór je beslist.
- **A. Cloudflare Pages + Cloudflare Access (Zero Trust, gratis tot 50 gebruikers).** Het dashboard alleen na inloggen met je e-mail. Kosten ±€0 per maand. Werk: de uitrolstap in `paper.yml` omzetten en een Cloudflare-account met API-token als secret. **Aanbevolen.**
- **B. GitHub Enterprise Cloud** (Pages met toegangscontrole). Ongeveer $21 per gebruiker per maand. Duur voor één gebruiker.
- **C. De repository privé maken.** Dan stoppen openbare Pages op het gratis plan; Pages vanaf een privé-repository vraagt minstens GitHub Pro (±$4 per maand) en is dan nog steeds openbaar. Lost P2 op, maar P3 niet.

## 7. Prestaties

Gemeten met Chromium headless op een lokale server, met de echte data van 23-11.

| Meting | Doel | Gemeten |
|---|---|---|
| Eerste inhoud (FCP) | < 1000 ms | desktop 52 ms, mobiel 48 ms (lokaal, zonder netwerkvertraging) |
| Pagina klaar (KPI's zichtbaar) | < 1500 ms | 146 ms en 137 ms |
| Wisselen van sectie | < 50 ms | max 12 ms |
| Klik in de graaf (opnieuw tekenen) | < 100 ms | 56 ms |
| `index.html` | < 100 kB, < 30 kB gzip | 67 kB, 20 kB gzip; 0 afhankelijkheden |
| `overmind.json` | < 300 kB, < 40 kB gzip | 153 kB, 16 kB gzip |
| Toegankelijkheid (axe-core, WCAG 2 A/AA) | 0 schendingen | 0 op 13 schermen (na 2 reparaties: contrast van de rode status, aria op de graaf) |
| Mobiel (390 px) | geen horizontale overloop | 0 op 13 schermen |

**Begrenzing.**
- De replay toont de laatste 60 beslissingen.
- De graaf bevat de laatste 40 beslissingen en 3 dagen meldingen. Standaard staan beslissingen, uitdagers en meldingen uit, omdat dat beter leesbaar is.
- De graaf wordt pas getekend op het eigen tabblad.

## 8. Onafhankelijke technische review

| # | Bevinding | Ernst | Gedaan |
|---|---|---|---|
| R1 | Coach-samenwerkingsregels stonden dubbel (bij beide afdelingen) in de radar, de graaf en de Academie | middel (misleidende telling) | opgelost en getest |
| R2 | Weekkeuzes zonder wijziging vervuilden de replay | laag | weggefilterd |
| R3 | De vasthoud-vergelijking bestaat alleen als eindgetal, niet als uurcurve. Daardoor heeft de grafiek één lijn. | middel (ontbrekende context) | eerlijk vermeld op het scherm; backlog B3 |
| R4 | Jarvis heeft geen tijdstempel in de data (`jarvis.json` bevat alleen een offset). Het bewijs komt daarom van GitHub, en buiten Pages staat Jarvis op ONBEKEND. | laag | backlog B4 |
| R5 | De radar-prioriteit is een eigen formule (bewijs × bevestiging × versheid). Die is transparant, maar niet gevalideerd als voorspeller van nut. | middel | gelabeld als "onderzoeksprioriteit, geen signaal" |
| R6 | De simulator rekent lineair, zonder correlatie- of liquiditeitsmodel, en de valutaschok gebruikt alleen USD-noteringen | middel | aannames staan bij elk scenario |
| R7 | Replay: de prijs "nu" tegen de vullingsprijs wordt alleen vergeleken bij EUR-noteringen. Bij andere munten staat "geen vergelijking". | laag | bewust; backlog B5 |
| R8 | Er zijn twee dashboards in de repository (HQ en NEXUS-web). Het Command Center vervangt NEXUS-web functioneel. | middel (dubbel werk) | voorstel: NEXUS-web bevriezen (CEO) |
| R9 | `index.html` is één bestand van 67 kB zonder build-stap. Goed voor Pages, maar groeit het verder, dan is opsplitsen nodig. | laag | backlog B7 |

## 9. Resterende blokkades en wat de CEO moet doen

1. **De PR beoordelen** en mergen of niet. Na merge publiceert de volgende ronde het Command Center op dezelfde Pages-URL. De stad blijft bereikbaar via de link "Stad".
2. **Privacy (P2 en P3):** kiezen tussen zo laten, A (Cloudflare Access, aanbevolen) of C (repository privé).
3. **Gepauzeerde afdelingen:** Crypto Lab en De Kluis blijven stil tot jij beslist.
4. **NEXUS-records:** een geplande `nexus-ops`-job die naar `paper-data` schrijft, vraagt jouw akkoord.
5. **AI:** sleutel en daglimiet, alleen als je dat wilt.

## 10. Innovatie-backlog (op prioriteit)

| # | Idee | Probleem | Nut voor de CEO | Techniek | Afhankelijk van | Risico | Omvang | Succesmaat |
|---|---|---|---|---|---|---|---|---|
| B1 | **Privé CEO-werkplek** (Cloudflare Access) | Alles is openbaar | Gevoelige details en echte knoppen kunnen veilig | Uitrol naar Cloudflare Pages en een Access-beleid | CEO-akkoord, account | Lage instelfout | S | Geen openbare toegang tot de portefeuille |
| B2 | **Geplande NEXUS-onderzoeksronde** | Intelligence staat op "niet verbonden" | Echte records in het dashboard en `/onderzoek` | `nexus-ops research` na elke ronde in Actions | B1 of akkoord | Schrijft naar `paper-data` | S | Hartslag "NEXUS" gezond; records per dag |
| B3 | **Vasthoud-curve per uur** opslaan | Geen tweede lijn in de grafiek | Direct zien wanneer we achter raakten | Benchmark-waarde per ronde in de equity-tabel (nieuwe kolom) | Raakt de boekhoudopslag: CEO-akkoord | Laag | S | Tweede lijn met dezelfde punten |
| B4 | **Jarvis-hartslag** in de data | Jarvis is ONBEKEND buiten Pages | Betrouwbare gezondheidsmelding | Tijdstempel in `jarvis.json` | – | Laag | XS | Hartslag "Jarvis" uit eigen data |
| B5 | **Replay-uitkomst in euro** voor alle munten | Geen vergelijking bij USD-noteringen | Eerlijke nameting voor aandelen en metalen | Wisselkoers (`fx_reference`) op het moment zelf | – | Laag | S | Alle beslissingen hebben een nameting |
| B6 | **"Sinds je laatste bezoek"** | Veranderingen zijn vast op 24 uur | Precies zien wat nieuw is | `localStorage`-tijdstempel en filter | – | Geen | XS | Minder tijd tot het eerste besluit |
| B7 | **Opsplitsen in modules** met snapshot-tests | Eén groot HTML-bestand | Onderhoudbaar | ES-modules zonder build en Playwright-regressie in CI | – | Laag | M | CI-browsertest groen |
| B8 | **Radar-prioriteit valideren** | Formule onbewezen | Weten of de radar helpt | Bijhouden welke vragen later echte verbeteringen werden | B2 | Laag | M | Aandeel radar-top-5 dat later promoveert |
| B9 | **Meetplan "VALIDATED"** voor het dashboard | Nut is niet gemeten | Bewijs dat het helpt | Telling (lokaal) van bezoeken naar besluiten en tijd tot besluit | – | Privacy: alleen lokaal | S | Tijd van pauze tot besluit |

## 11. Volgende milestone (voorstel 10.0, alleen na akkoord)

**"Private Operations":**
- B1 privé-werkplek.
- B2 NEXUS-ronde.
- B3 en B4 de ontbrekende hartslag en curve.
- Daarna, achter inloggen, een eerste geauthenticeerde actie: een hervatverzoek dat de CEO in Telegram moet bevestigen.

De handelsengine blijft daarbij ongewijzigd.
