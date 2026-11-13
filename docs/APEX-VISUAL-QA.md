# APEX · Visuele QA (D8)

Werkwijze: productie-build (`next build` + `next start`) tegen de API met de echte holding-data en een
e2e-database met één fixture-gebeurtenis (`[FIXTURE]`, als gesimuleerd gelabeld). Playwright/Chromium.
Viewports: desktop 1440×900, tablet 834×1112, mobiel 390×844 (pixelratio 2).

**Er zijn geen screenshots gemaakt of bewerkt buiten deze runs.** Alle beelden staan in de projectmap
`/mnt/project-files/nexus-ai/research/milestone-d/screenshots/` (`before/` = vóór D, `after/` = na D).

## Resultaat per route (laadtijd tot netwerk stil, ms)

| Route | Desktop | Tablet | Mobiel | Overloop | Consolefouten |
|---|---|---|---|---|---|
| `/` Command Center | 1440 | 1222 | 1185 | nee | 0 |
| `/crypto` | 1553 | 1093 | 975 | nee | 0 |
| `/stocks` | 1417 | 1123 | 1019 | nee | 0 |
| `/forex` | 1352 | 1163 | 1012 | nee | 0 |
| `/meme` | 1308 | 1043 | 1012 | nee | 0 |
| `/hq` AI HQ | 1368 | 973 | 766 | nee | 0 |
| `/decisions` Decision Theater | 968 | 810 | 681 | nee | 0 |
| `/news` News Reactor | 1152 | 944 | 766 | nee | 0 |
| `/social` Social Radar | 1095 | 878 | 705 | nee | 0 |
| `/pulse` Market Pulse | 1072 | 1543 | 1152 | nee | 0 |
| `/evolution` (plus Arena-tab, desktop en mobiel) | 976 | 718 | 658 | nee | 0 |
| `/operations` | 1247 | 1062 | 942 | nee | 0 |

38 screenshots, 0 consolefouten, 0 keer horizontale overloop. De laadtijden zijn lokaal gemeten. Ze bevatten het wachten tot
het netwerk stil is, inclusief de periodieke API-aanroepen, en zijn dus een bovengrens.

## Gevonden en opgelost tijdens QA

| Probleem | Waar | Oplossing |
|---|---|---|
| Afdelingslabels overlapten rollabels | AI HQ, Neural Core | Sectorbogen en labels binnen de ring geplaatst |
| Tekst van de stapkaarten liep over ("Marktgebeurtenis") | Decision Theater | 2 → 3 → 5 → 9 kolommen per breekpunt, woordafbreking (`lang="nl"`, `hyphens-auto`) |
| Prioriteitsblok stond scheef naast de titel | Decision Theater | flex-basis voor de titel, blok links op smalle schermen |
| Kolommen te smal, sticky verschoof de inhoud | Workstation 1440 | Lay-out met 2 kolommen tot 1760 px en 3 daarboven; sticky verwijderd |
| Grafiek stond onder de watchlist op tablet en mobiel | Workstation | Volgorde: grafiek, watchlist, onderzoek |
| RSI-paneel te plat | Workstation | Paneelverhouding 3:1 |
| Watchlist-labels op drie regels | Workstation | Korter ("extra"), afgekapt met uitleg eronder en in een tooltip |
| Horizontale overloop op mobiel | `/`, `/pulse`, `/operations` | `min-w-0` op elk `Panel`; segmentknoppen lopen door op een nieuwe regel |
| Contrast bijschrift 4,0:1 en zachtste tekst 2,3:1 | hele app | slate-500 → #7E8798 (5,2:1), slate-600 → #788192 (4,8:1) |

## Toegankelijkheid

* **Contrast:** alle tekstkleuren ≥ 4,5:1 op het paneel (tabel in `APEX-DESIGN-SYSTEM.md`).
* **Toetsenbord:** Neural Core-knopen zijn focusbaar en Enter/Spatie opent het dossier. De Drawer sluit met Esc en zet de focus erin. Tabs en knoppen geven hun toestand door met `aria-selected` of `aria-pressed`.
* **Alternatieven:** Neural Core heeft een Lijst-weergave. Grafieken hebben `role="img"` met een label, en de gemeten kenmerken staan ernaast als tekst. De correlatiematrix toont de waarde bij hover en in een `title`.
* **Beweging:** elke animatie staat in de `prefers-reduced-motion`-lijst.
* **Niet getest:** een echte schermlezer (NVDA/VoiceOver) en een automatische axe-scan. Die staan als vervolgwerk genoteerd.

## Prestaties

| Meting | Waarde |
|---|---|
| JS-bundel totaal (alle routes, ongecomprimeerd) | 1,2 MB; grootste chunks gzip 72 / 58 / 47 / 39 kB |
| Lightweight Charts-chunk | 179 kB, 58 kB gzip |
| JS overgedragen bij het openen van `/crypto` | 293 kB |
| Statische HTML per route | 16 – 22 kB |
| TTFB / FCP (`/crypto`) | 7 ms / 228 ms |
| Grafiek zichtbaar (`/crypto`) | 1,3 s |
| Interactie (bereik, tijdschaal, candles) | 0,13 – 0,26 s inclusief Playwright-overhead |
| API `workstation/universe` | 130 ms |
| API `workstation/asset` (750 dagen) | 32 ms |
| API `market/overview` | 295 ms (37 reeksen en correlatie) |
| API `hq/handoffs`, `hq/agents/{rol}`, `central/org` | 5 – 10 ms |

## CI

Nieuwe job `nexus-visual` in `.github/workflows/ci.yml` (niet blokkerend, `continue-on-error`):
1. Start de API in de **demo-omgeving** (`NEXUS_DEMO=1`): synthetische data, geen sleutels, live uit. Elk versheidslabel wordt daar SIMULATED.
2. Bouwt en start de web-app.
3. `e2e/visual-smoke.mjs` bezoekt 12 routes op 3 viewports. De job faalt bij een consolefout of horizontale overloop.
4. De screenshots en `timing.json` worden als artefact `nexus-visual-smoke` bewaard (14 dagen).

**Geen pixelvergelijking.** Tijdstempels en koersen veranderen per run, dus vaste pixel-baselines zouden vals alarm geven.
Dat kan pas met een bevroren fixture-API (zie de tool-evaluatie).
