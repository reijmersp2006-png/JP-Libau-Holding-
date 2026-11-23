# Master Prompt 9.1: beveiliging en deploy-verificatie

Stand: 23 november 2026, 21:45 UTC. Statuswoorden: IMPLEMENTED / TESTED / DEPLOYED / OPERATIONAL / BLOCKED.
In dit rapport staat nergens de waarde van een geheim of identificatienummer.

## 1. Productiestatus (echt gecontroleerd)

| Onderdeel | Status | Bewijs |
|---|---|---|
| PR #34 in `main` | DEPLOYED | merge-commit `511b111` (21:15 UTC); CI op `main`: tests, nexus, nexus-visual, backtest, databronnen groen |
| Command Center live | DEPLOYED | paper-run 45269560188 (21:26 UTC, build `511b111`) publiceerde `index.html`, `stad.html`, `overmind.json`, `state.json`, `snapshot.json`, `factsheet.html`, `jarvis.html`; deploy-pages "Reported success" |
| Verse data | OPERATIONAL | `paper-data` `be1a4a2` 21:26 UTC; overmind-pulse: handelsronde, koersen 1u/1d, verkenners, risico, academie, coach, arena, snapshot HEALTHY; feeds DEGRADED; Jarvis/publicatie UNKNOWN (geen bewijs in de data = geen groen); NEXUS/AI BLOCKED |
| Vijf secties, desktop + mobiel | TESTED | gebouwd met dezelfde code en dezelfde productiedata: 13 routes × 2 schermen, 0 consolefouten, 0 overloop, 0 axe-schendingen (WCAG 2 A/AA), graafklik, simulator en replay werken |
| Uurronde | OPERATIONAL | laatste 6 rondes succesvol; ze starten via de Jarvis-wachter (`workflow_dispatch`), de cron van :17 komt zelden aan |
| Jarvis (elke 10 min) | OPERATIONAL | laatste 6 runs succesvol; hartslag-keten actief sinds 15:48 UTC |
| Jarvis-commando's | TESTED | `/stand`, `/aandacht`, `/veranderd`, `/systeem`, `/pauze`, `/pauze crypto`, `/pauze metals`, `/onderzoek`, `/help` op de echte productiedata: allemaal antwoord, niets veranderd (KILL en afdelingsdatabases byte-gelijk) |
| Risicolimieten | ongewijzigd | 15% drawdown, 3% daglimiet, 25% per positie, 90% belegd, 10 trades/dag: geen diff in config, holding, risk, strategy of portfolio sinds 8.0 |
| Pauzes | ongewijzigd | Crypto Lab (15,6%) en De Kluis (15,1%) staan nog stil; niets hervat |

**Verschillen tussen code, tests en productie**

1. Tussen de merge (21:15) en de eerste ronde daarna (21:26) draaide productie nog de 8.0-site. Dat hoort zo: Pages ververst alleen bij een ronde.
2. Ik kon `github.io` niet zelf openen, want het netwerkbeleid van mijn werkomgeving blokkeert die host. Het bewijs is daarom: de deploy-log met de bestandslijst, plus dezelfde build lokaal getest op dezelfde data.
3. De uurronde hangt in de praktijk aan de Jarvis-wachter, niet aan de cron. Dat werkt, maar het is één keten (zie B3).
4. Telegram zelf kon ik niet testen: ik kan geen bericht als Phil sturen. Wel is de Jarvis-workflow groen, en dezelfde code geeft op de echte data de juiste antwoorden.

## 2. Bevindingen naar ernst

**Er zijn geen echte geheimen gelekt.** Ik heb deze bronnen doorzocht op Telegram-bottokens, GitHub-tokens, AI-sleutels, AWS-sleutels, private keys en tokens in URL's:

- alle 377 commits van `paper-data`
- de hele geschiedenis van `main`
- de publieke site
- de Actions-logs

Er is niets gevonden, behalve placeholders (`${TOKEN}`) en een nep-testwaarde. Er is dus **geen urgente rotatie** van sleutels nodig.

| # | Ernst | Bevinding | Impact | Prioriteit |
|---|---|---|---|---|
| F1 | **Middel** | De Telegram-chat-id van Phil (= Telegram-gebruikers-id) staat in de publieke branch `paper-data`, in `data/holding.sqlite3`, en daarmee in **elke** commit van die branch | Phil is op Telegram te identificeren en te benaderen (spam, social engineering). Jarvis besturen kan er **niet** mee: Telegram bevestigt zelf de afzender, en het bottoken staat alleen in de Actions-geheimen | 1 |
| F2 | **Middel** | De volledige operationele databases zijn publiek: `holding.sqlite3` (48k koersen, 14.840 radar-regels, alarmen, voorspellingen, academie, coach, arena, risicostaat) en 5 afdelingsdatabases (fills, equity, posities, pauzeredenen, selectiescores, aanpassingen) | Strategie, beslissingen en parameters zijn na te bouwen. Geen financieel verlies, want het is nepgeld | 2 |
| F3 | Laag-middel | De journals `logs/*/journal-*.jsonl` zijn publiek | Elke beslissing met reden is te volgen | 2 |
| F4 | Laag | Het publieke dashboard (`state.json`, `snapshot.json`, `overmind.json`) toont portefeuille, equity, pauzes en briefing | Bewust publiek tot de Cloudflare-keuze. Gecontroleerd: 0 keer de chat-id, 0 lokale paden, 0 verboden sleutels | 3 |
| F5 | Laag | Jarvis pakte bij een ontbrekende chat-id de laatste privé-afzender als eigenaar (`find_chat`) | Als de chat-id ooit wegvalt, kan een vreemde de briefings krijgen. **Verholpen** in deze PR | 1 |
| F6 | Laag | `jarvis.json` (Telegram-offset) staat publiek | Geen geheim en niet misbruikbaar | 4 |
| F7 | Laag | Interne onderzoeksrecords (`nexus/research/*`: audits, holdout, genesis) staan in de publieke code-repo | Onderzoeksmethode zichtbaar, geen persoonsgegevens | 4 |
| F8 | Info | De Actions-logs zijn publiek | Gecontroleerd: geheimen staan gemaskeerd (`***`). Wel zichtbaar zijn de potjesbedragen per afdeling | 4 |
| F9 | Info | De voornaam "Phil" staat in docs/README. Er staan geen e-mailadressen of lokale paden in de getrackte bestanden | Verwaarloosbaar | 5 |

## 3. Inventaris publieke blootstelling

| Plek | Wat | Gevoelig? |
|---|---|---|
| `main` (code) | broncode, workflows, docs, `nexus/research` | Nee (F7, F9) |
| `paper-data` (377 commits) | `data/holding.sqlite3`, `data/desks/*.sqlite3`, `logs/*/journal-*.jsonl`, `jarvis.json`, eventueel `KILL` | **Ja** (F1, F2, F3) |
| GitHub Pages | precies 7 bestanden (zie allowlist) | Portefeuille ja (F4), identiteit nee |
| Actions-logs en -artefacten | rondelogs, backtest-rapport, Pages-zip (1 dag) | Laag (F8) |
| Forks en klonen | alles wat ooit op `paper-data` stond | Niet terug te halen; vooral F1 |

## 4. Veilige maatregelen in deze PR

Allemaal IMPLEMENTED en TESTED. Zonder nieuwe instellingen gedraagt alles zich precies als nu.

1. **Poortwachter voor de publicatie** (`jplh publish-check`, `src/jplh/security.py`).
   - Er gaat alleen iets naar Pages als het op de expliciete allowlist staat: `index.html`, `stad.html`, `factsheet.html`, `jarvis.html`, `state.json`, `snapshot.json`, `overmind.json`.
   - Databases, logboeken, verboden JSON-sleutels (zoals chat, token, secret en offset), bekende geheimen (tokens uit de omgeving en de opgeslagen chat-id), tokenpatronen en lokale paden worden geblokkeerd.
   - De stap draait in `paper.yml` **na** "Stand bewaren": als hij faalt, blijft alleen het dashboard offline, terwijl de handel en de stand gewoon doorgaan. Rapporten maskeren elke waarde.
2. **Chat-id als geheim** (`TELEGRAM_CHAT_ID`).
   - Staat dat geheim klaar, dan gebruikt Jarvis het en haalt hij de chat-id uit de opgeslagen stand. Nieuwe commits bevatten hem dan niet meer.
   - Er komt geen dubbele welkomstgroet.
   - F5 is verholpen: na de eerste koppeling neemt Jarvis nooit meer automatisch een vreemde afzender als eigenaar aan.
3. **Privé-opslag van de stand, opt-in** (variabele `STATE_REPO` + geheim `STATE_TOKEN`).
   - `paper.yml` en `jarvis.yml` halen en bewaren de stand dan in een privé-repo, in plaats van op de publieke `paper-data`.
   - Is die opslag onbereikbaar of leeg, dan **stopt** de ronde. Hij begint nooit stil opnieuw met een lege portefeuille.
   - Zonder de variabele: precies als nu.
4. **Geheimenscan in CI** (`jplh secret-scan $(git ls-files)`) plus een test die hetzelfde controleert. Placeholders en `.env.example` mogen; echte vormen niet.
5. **De handelsmotor blijft los van de publicatie**: de publicatie is een aparte, latere stap. Strategie, orders, boekhouding, risicolimieten en live-instellingen zijn niet aangeraakt.

## 5. Acties die jouw akkoord nodig hebben

| # | Actie | Waarom | Kosten |
|---|---|---|---|
| A1 | Deze PR reviewen en mergen | Activeert de poortwachter en de CI-scan | 0 |
| A2 | Repo-geheim `TELEGRAM_CHAT_ID` toevoegen (Settings, Secrets and variables, Actions) | Vanaf de eerstvolgende ronde staat de chat-id niet meer in nieuwe commits | 0 |
| A3 | Privé-repo aanmaken (bijv. `jplh-state`), de huidige stand erheen pushen, een fine-grained token (alleen die repo, Contents: Read and write) als `STATE_TOKEN` en de repo-naam als variabele `STATE_REPO` | Haalt F2 en F3 weg uit nieuwe commits. Alleen de **data** gaat privé, de code-repo blijft publiek, zodat Actions-minuten gratis blijven (zie §6) | 0 |
| A4 | Na A3 en een week stabiel: de branch `paper-data` verwijderen en GitHub Support vragen om gecachte objecten te wissen | De geschiedenis blijft anders publiek. Een geschiedenis-rewrite of verwijdering doe ik niet zonder jou | 0 |
| A5 | Accepteren dat de chat-id permanent bekend kan zijn | Een Telegram-id kun je niet wisselen, en klonen en forks kunnen hem al hebben. Restrisico: laag | 0 |
| A6 | Cloudflare Pages + Access (§6) | Het dashboard achter een login | $0 (Free) |
| A7 | Crypto Lab en De Kluis | Blijven stil tot jij `jplh resume` doet | n.v.t. |

## 6. Migratieplan: Cloudflare Pages + Cloudflare Access

**Belangrijk:** een login voor het dashboard helpt alleen als ook de data zelf niet meer op GitHub staat. Volgorde: eerst A2 en A3, pas dan Cloudflare.

**Geverifieerde prijzen en beperkingen (23-11-2026):**

- **Zero Trust Free:** $0, "forever", tot **50 gebruikers**, logs tot **24 uur**. Pay-as-you-go kost $7 per gebruiker per maand (30 dagen logs). De prijspagina noemt Access niet als losse regel, maar "Zero Trust Network Access (ZTNA)" staat op Free als "Included". **Controleer bij het aanmaken** dat er een Access-applicatie op Free kan; een betaalkaart wordt op de pagina niet genoemd.
- **Pages Free:**
  - 500 builds per maand en 1 build tegelijk.
  - 20.000 bestanden per site en 25 MiB per bestand.
  - 100 projecten per account.
  - Of uploads via wrangler (Direct Upload) meetellen voor de 500 builds, staat niet in de documentatie. Wij zouden ~720 uploads per maand doen. Als ze meetellen: dashboard elke 2 uur publiceren (~360), of Pro nemen.
- Direct Upload kan later **niet** omgezet worden naar Git-integratie. Dat is prima, want wij bouwen in Actions.
- Access op `*.pages.dev`: het vinkje "Enable access policy" beschermt alleen **previews**. Voor het productiedomein moet je in de Access-applicatie bij "Public hostname" het `*` in Subdomain weghalen, en daarna de preview-policy opnieuw aanzetten. Een eigen domein vraagt een aparte self-hosted Access-app.
- GitHub Free geeft privé-repos een beperkt aantal Actions-minuten. Onze hartslag draait vrijwel continu, dus de code-repo moet **publiek blijven**. Alleen de data-repo wordt privé; die draait zelf geen workflows.

**Ontwerp:**

- **Authenticatie:** een Access-app op `<project>.pages.dev`, policy "Allow" op Phil's e-mailadres, login met een eenmalige pincode per e-mail (geen extra account), sessie 24 uur. Later eventueel ook GitHub als identiteitsprovider.
- **Privé-opslag:** de stand in de privé-repo (A3). De site wordt in Actions gebouwd en direct geüpload, zodat de data nergens publiek staat.
- **Machinetoegang (NEXUS, later):** een Access service token (`CF-Access-Client-Id` en `-Secret`) als geheim. Zo hoeft er nooit een publieke route terug.
- **Workflow:** in `paper.yml` komt dit in plaats van de drie Pages-stappen, na `jplh publish-check`:

  ```yaml
  - uses: cloudflare/wrangler-action@v4
    with:
      apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
      command: pages deploy site --project-name=jplh-hq --branch=main
  ```

- **Benodigde geheimen:** `CLOUDFLARE_API_TOKEN` (Account, Cloudflare Pages: Edit, verder niets), `CLOUDFLARE_ACCOUNT_ID`, plus `STATE_TOKEN` / `STATE_REPO` en `TELEGRAM_CHAT_ID`.
- **Stappen:**
  1. Cloudflare-account en Zero Trust-organisatie (Free).
  2. `wrangler pages project create jplh-hq`.
  3. Access-app en policy instellen, `*.pages.dev` mee laten beschermen.
  4. Testen in een incognitovenster: zonder login moet je een 302 naar Access krijgen.
  5. Workflow-PR mergen.
  6. Eén ronde controleren.
  7. GitHub Pages uitzetten (Settings, Pages, Unpublish).
- **Kosten:** $0 bij Free. Er kan $7 per gebruiker per maand bijkomen als je langere logs wilt.
- **Terugdraaien:**
  - De Pages-stappen staan in git en zijn met een revert terug.
  - GitHub Pages weer aanzetten.
  - De Access-app uitzetten geeft het pages.dev-domein weer vrij. Doe dat alleen bewust.
  - De privé-opslag terugdraaien = de variabele `STATE_REPO` leegmaken. De publieke branch is dan wel verouderd: eerst de privé-stand terug-pushen.

## 7. Regressietests

| Suite | Resultaat |
|---|---|
| jplh (`pytest -q`) | **165 geslaagd** (154 bestaande + 11 nieuwe in `tests/test_security.py`) |
| NEXUS backend | **215 geslaagd** |
| Geheimenscan getrackte bestanden | 258 bestanden, 0 bevindingen |
| `publish-check` op de echte productiesite | veilig, 0 bevindingen (de opgeslagen chat-id telt mee als bekend geheim) |
| Browser-QA op dezelfde productiedata | desktop + mobiel: 0 fouten, 0 overloop, 0 axe; FCP 36-72 ms |
| Jarvis-commando's op productiedata | 9 van 9 antwoorden, niets gewijzigd |

De nieuwe tests dekken:

- de allowlist
- het blokkeren van databases en logboeken
- verboden sleutels, bekende geheimen, lokale paden en tokenvormen, terwijl het rapport nooit de waarde toont
- placeholders tegenover echte sleutels
- de exitcodes van de CLI
- de chat-id uit de stand bij een geheim, zonder dubbele groet
- geen vreemde eigenaar
- workflow-volgorde (eerst de stand bewaren, dan pas de poortwachter, en pas daarna publiceren)
- het stoppen bij een lege privé-opslag
- een schone repo

Geplande schema's na de merge: geen wijziging in cron of concurrency. Rondes en Jarvis lopen door zoals nu.

## 8. Uitrol en terugdraaien

- **Uitrol:**
  1. Merge.
  2. De eerstvolgende ronde draait de poortwachter.
  3. A2 (chat-id-geheim), daarna de volgende ronde controleren: in `paper-data` ontbreekt `telegram.chat`.
  4. A3 (privé-opslag), daarna een ronde en een Jarvis-run controleren, en dat `paper-data` niet meer verandert.
  5. Cloudflare (§6).
- **Terugdraaien:** de PR reverten. De geheimen en variabelen mogen blijven staan; zonder de nieuwe code worden ze genegeerd. Als de poortwachter onterecht blokkeert, gaat de handel gewoon door: alleen het dashboard is dan verouderd, en de rondefout-melding komt via Telegram.

## 9. Resterende blokkades

- B1: de geschiedenis van `paper-data` bevat de chat-id en alle data. Opruimen vraagt jouw akkoord (A4).
- B2: Cloudflare-account en -instellingen kan alleen jij aanmaken.
- B3: de uurronde hangt aan de Jarvis-wachter, omdat de GitHub-cron onbetrouwbaar is. Hij werkt wel, maar Jarvis en de hartslag zijn samen één keten.
- B4: Telegram-commando's kon ik niet end-to-end testen vanuit mijn omgeving.

## 10. Gereedheid voor Milestone 10.0

**Nog niet klaar voor echte AI-activering. Wel klaar zodra A1 tot en met A3 gedaan zijn.**

- Gereed:
  - Er zijn geen gelekte sleutels.
  - De publicatie gaat via een allowlist en een poortwachter.
  - De CI-geheimenscan draait.
  - De handel staat los van het dashboard.
  - Alle tests zijn groen.
- Nodig vóór AI:
  - A2 en A3: geen persoonsgegevens en operationele data meer in publieke commits.
  - Bij voorkeur A6: AI-uitvoer en onderzoeksrecords horen achter een login, niet op een publieke site.
  - AI-sleutels alleen als Actions-geheim of in de NEXUS-omgeving, nooit in de stand. De poortwachter herkent `sk-`-sleutels al.
