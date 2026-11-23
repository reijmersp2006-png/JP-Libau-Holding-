# Security-activatie 9.2: de stand privé, met bewijs

Dit is het draaiboek. Het verslag van wat er echt gebeurd is (met run-nummers) komt onderaan
bij **Uitvoering**. Er staat nergens een geheim of identificatienummer in.

## 0. Uitgangssituatie (23-11-2026, 21:36 UTC)

- `main` = `13e71e2`: PR #35 zit erin, CI is groen.
- Er heeft nog geen handelsronde met die code gedraaid. De laatste ronde was `be1a4a2` om 21:26 UTC.
- Ingestelde geheimen (afgeleid uit de stand en de logs, zonder waarden):
  - `TELEGRAM_CHAT_ID`: nog niet. De chat-id staat nog in de stand.
  - `STATE_TOKEN` en `STATE_REPO`: nog niet. Rondes bewaren nog op de publieke `paper-data`.
- Vingerafdruk van de echte stand (`jplh state-check`, alleen-lezen):

  | Onderdeel | Waarde |
  |---|---|
  | Bestanden | 26 bestanden, 12,3 MB |
  | Databases | 6, integriteit allemaal `ok` |
  | Journals | 19 bestanden, 84 regels |
  | Vermogen | €916,68 |
  | Crypto Lab | €256,85, 0 posities, **gepauzeerd** |
  | Meme Arcade | €45,22, 0 posities |
  | Aandelen | €337,18, 5 posities |
  | De Kluis | €130,75, 2 posities, **gepauzeerd** |
  | Wisselhaven | €146,68, 4 posities |
  | Noodstop (`KILL`) | nee |

## 1. Wat deze PR toevoegt

- **`jplh state-check`**: een vingerafdruk van de stand.
  - sha256 van elk bestand in `data/`, `logs/`, `jarvis.json` en `KILL`.
  - `PRAGMA integrity_check` per database.
  - Vermogen, cash, posities, pauzes en trades per afdeling.
  - `--against` vergelijkt twee kopieën. De hashes worden vastgelegd vóór er iets geopend wordt.
- **`jplh config-check`**: zegt alleen ja of nee per instelling. Het ziet ook of het chat-id-geheim klopt met de gekoppelde chat. Draait elke 10 minuten in Jarvis, dus de logs zijn het runtime-bewijs.
- **Verkeerd ingevuld chat-id-geheim**: wijkt `TELEGRAM_CHAT_ID` af van de al gekoppelde chat, dan wordt het geheim genegeerd en blijft de koppeling staan. Eén typefout kan je dus nooit buitensluiten.
- **Workflow "Stand verhuizen"** (alleen met de hand te starten, nooit tegelijk met een ronde):
  - `controle`: test lezen, schrijven en opruimen op een tijdelijke branch en bewijst met hashes dat een kopie identiek is. De echte stand blijft onaangeroerd.
  - `verhuizen` (typ `VERHUIS`):
    - Kopieert `paper-data` mét geschiedenis naar de privé-repo.
    - Zet een `MOVED`-markering op de publieke branch.
    - Bewijst dat beide kopieën identiek zijn en haalt late Jarvis-commits in.
    - Weigert als de privé-repo een afwijkende stand heeft, en weigert een publieke doel-repo.
  - `terugzetten` (typ `TERUG`): rollback. De privé-stand (inclusief latere rondes) gaat terug naar de publieke branch en de markering verdwijnt.
- **Beveiliging tegen een verouderde kopie**: zonder `STATE_REPO` weigeren ronde en Jarvis een stand met `MOVED`. Ze bouwen dus nooit verder op een oude kopie.
- **Publicatie**: een tweede poging als GitHub het Pages-artefact niet vindt (zie §5).

Alles is getest: 6 tests in `tests/test_migrate.py` voeren de bash-stappen uit de workflow letterlijk uit tegen echte git-repo's.

## 2. Jouw stappen in GitHub (één voor één)

**Stap 1: privé-repo aanmaken** (veilig, verandert nog niets)

1. Klik op github.com rechtsboven op **+** en kies **New repository**.
2. Owner: jouw account. Repository name: `jplh-state`.
3. Kies **Private**.
4. Voeg niets toe: geen README, geen .gitignore, geen licentie. De repo moet leeg zijn.
5. Klik op **Create repository**.

**Stap 2: sleutel met minimale rechten**

1. Klik rechtsboven op je profielfoto en kies **Settings**.
2. Klik links helemaal onderaan op **Developer settings**, dan **Personal access tokens**, dan **Fine-grained tokens**, dan **Generate new token**.
3. Token name: `jplh-state`. Expiration: **Custom**, 1 jaar. Noteer de datum.
4. Repository access: **Only select repositories**, en kies alleen `jplh-state`.
5. Bij **Permissions**, **Repository permissions**: zet **Contents** op **Read and write**. **Metadata: Read** gaat vanzelf mee. Verder niets.
6. Klik op **Generate token** en kopieer hem. Hij is maar één keer zichtbaar. Plak hem nergens anders dan in stap 3.

**Stap 3: geheim in de holding-repo**

1. Open `JP-Libau-Holding-`, klik op **Settings**, dan links op **Secrets and variables**, dan **Actions**.
2. Klik op **New repository secret**. Name: `STATE_TOKEN`. Secret: de token uit stap 2. Klik op **Add secret**.

**Stap 4: chat-id als geheim**

1. Zoek je eigen Telegram-id op. Officiële weg: Telegram Desktop, **Settings**, **Advanced**, **Experimental settings**, zet **Show Peer IDs in Profile** aan; daarna staat het id in je profiel.
2. Op dezelfde pagina als stap 3: **New repository secret**. Name: `TELEGRAM_CHAT_ID`.
3. Een typefout kan geen kwaad: Jarvis negeert een afwijkend geheim. `config-check` laat het zien.

**Stap 5: controle-run** (doe ik samen met jou)

Open **Actions**, kies **Stand verhuizen**, klik op **Run workflow**. Stand: `controle`, doel: `<jouw-naam>/jplh-state`. Ik lees de uitkomst en bevestig.

**Stap 6: verhuizen.** Pas na mijn akkoord op stap 5.

1. Zelfde workflow. Stand: `verhuizen`, bevestiging: `VERHUIS`.
2. Direct daarna: **Settings**, **Secrets and variables**, **Actions**, tabblad **Variables**, **New repository variable**. Name: `STATE_REPO`, value: `<jouw-naam>/jplh-state`.
3. Tussen deze twee klikken weigert een ronde te draaien. Daarvoor kan één Telegram-melding "ronde mislukt" komen. Dat is de beveiliging, geen storing.

**Stap 7: bewijs.** Ik controleer de eerstvolgende ronde en Jarvis-run (logs, `config-check`, vingerafdruk in de privé-repo) en dat de publieke `paper-data` stil blijft.

**Terugdraaien:** workflow **Stand verhuizen** met stand `terugzetten` en bevestiging `TERUG`. Maak daarna `STATE_REPO` leeg. Let op: daarmee staat de data weer publiek.

## 3. Wat ik niet doe zonder jouw expliciete akkoord

- De publieke branch `paper-data` verwijderen of de geschiedenis herschrijven.
- De pauzes van Crypto Lab en De Kluis opheffen.
- Iets aan strategie, risico of portefeuille veranderen.
- Betaalde diensten aanzetten.

## 4. Gereedheidscriteria voor 10.0 (Project Awakening)

| # | Criterium | Bewijs dat ik lever |
|---|---|---|
| R1 | Stand alleen nog privé | Twee rondes en twee Jarvis-runs in de privé-repo. Publieke `paper-data` heeft na `MOVED` geen nieuwe commits |
| R2 | Chat-id niet meer in nieuwe commits | `config-check`: "geheim klopt"; `telegram_fields` zonder `chat` |
| R3 | Stand compleet verhuisd | `state-check --against`: IDENTIEK (digest, bestanden, integriteit, vermogen, pauzes) |
| R4 | Publieke export veilig | `publish-check` in elke ronde groen; 0 bevindingen |
| R5 | Geen geheimen in code | CI-geheimenscan groen |
| R6 | Handel onaangetast | Vermogen en posities sluiten aan, pauzes ongewijzigd, risicolimieten zonder diff |

## 5. Planner: betrouwbaarheid en voorstel

**Gemeten over 300 rondes (12 tot 23 november):**

- 260 rondes gestart door de Jarvis-wachter, maar 40 door de cron. De cron van :17 komt dus maar ~13% van de keren aan.
- 290 rondes geslaagd. Van de 10 mislukte waren er **9 alleen de publicatie**: GitHub vond het Pages-artefact niet ("No artifacts named github-pages"). De handel en de stand waren dan al opgeslagen. Er was **1 echte rondefout** (19 november).
- Dubbele rondes komen voor: cron en wachter kunnen in hetzelfde uur allebei een ronde starten (bijvoorbeeld 21:09 en 21:25). De vermogenscurve telt per uur, maar er kan twee keer per uur gehandeld worden.

**Single points of failure:**

1. Alles draait in GitHub Actions van één repo. Een storing of het uitschakelen van Actions legt alles stil.
2. De keten hartslag ⇄ Jarvis ⇄ ronde: als zowel de hartslag als de Jarvis-cron wegvallen, start niemand de ronde meer. GitHub zet geplande workflows bovendien uit na 60 dagen zonder activiteit in de repo. Of de commits op `paper-data` (of straks de privé-repo) daarvoor meetellen, moet nog gecontroleerd worden.
3. Er is geen bewaking van buitenaf: als GitHub zelf stilvalt, meldt niemand het.

**Voorstel** (A en B ingebouwd, C tot en met E wachten op jouw akkoord):

- **A. Publicatie herkansen** (in deze PR): een tweede deploy-poging na 30 seconden. Dit lost de meeste "mislukte rondes" op.
- **B. Draaiboek en vingerafdruk** (in deze PR): gezondheid is aantoonbaar per ronde.
- **C. Idempotente ronde**: een ronde slaat zichzelf over als er minder dan 45 minuten geleden een geslaagde ronde was. Dan zijn meerdere triggers veilig en vallen dubbele rondes weg. Dit verandert het ritme van handelen, niet de strategie. Daarom wacht ik op je akkoord.
- **D. Onafhankelijke trigger**: een Cloudflare Worker met Cron Trigger (Free plan) roept elke 15 minuten `workflow_dispatch` aan, met een eigen fine-grained token (Actions: write, alleen deze repo). Samen met C is dat een tweede, losstaande klok.
- **E. Bewaking van buitenaf**: elke geslaagde ronde pingt een gratis heartbeat-check (bijv. healthchecks.io). Blijft de ping 90 minuten uit, dan krijg je een melding, ook als GitHub zelf plat ligt.

Kosten van D en E: €0 op de gratis plannen. Wel twee nieuwe externe accounts, dus jouw beslissing.

## Uitvoering

*(wordt ingevuld met run-nummers en uitkomsten zodra de stappen gedaan zijn)*
