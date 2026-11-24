# 9.3 Infrastructuurherstel en weerbaarheid

Stand op 24-11-2026, 15:00 UTC. Er staat nergens een geheim of identificatienummer in.

## A. Telegram: root cause

**Bewijs.** Jarvis-run 45417186097 (14:43 UTC, eerste run met de diagnose uit PR #37):

```
Jarvis: Telegram getUpdates mislukt: HTTP 404 Not Found
```

De `config-check` in dezelfde run: `TELEGRAM_TOKEN aanwezig: ja`, `TELEGRAM_CHAT_ID aanwezig: ja`.

**Wat 404 betekent.** Telegram geeft per toestand een andere code:

| Code | Betekenis |
|---|---|
| 401 Unauthorized | De token heeft de juiste vorm, maar is ingetrokken of vervangen. |
| 409 Conflict | Er staat een webhook, of er pollt een ander proces tegelijk. |
| 404 Not Found | Telegram herkent het adres niet: het geheim heeft niet de vorm `<cijfers>:<35 tekens>`. |

Een 404 betekent dus géén conflict met een webhook of een tweede bot, en ook géén ingetrokken token.

Het geheim `TELEGRAM_TOKEN` bevat sinds 24-11 rond 10:52 UTC iets anders dan de bottoken. Mogelijke oorzaken:

- een spatie of regeleinde;
- `bot` ervoor;
- een half geplakte token;
- de chat-id in het verkeerde vak.

De eerste mislukte run valt samen met het instellen van `TELEGRAM_CHAT_ID`. Waarschijnlijk is daarbij het tokengeheim overschreven. Dat is een afleiding uit de timing; de 404 zelf is gemeten.

**Gevolg.**

- `/noodstop` en de andere commando's via Telegram werken sinds 10:52 niet.
- Meldingen van de rondes komen ook niet aan.
- De handel zelf liep gewoon door. De rondes van 13:00 en 14:00 slaagden, want de wachter draait met `if: always()`.

**Herstel** (bestaande bot, geen nieuwe bot, chat en commando's blijven):

1. Open in Telegram **@BotFather**, stuur `/mybots`, kies de Jarvis-bot en tik op **API Token**. Dit toont de bestaande token. Kies **niet** "Revoke".
2. Ga in GitHub naar **Settings → Secrets and variables → Actions → TELEGRAM_TOKEN → Update**. Plak alleen de token: geen spatie, geen `bot` ervoor, geen regeleinde.
3. Binnen 10 minuten draait Jarvis. Na deze PR toont de stap "Gezondheid" `Telegram API HEALTHY token geldig, geen webhook`. Als het nog fout gaat, staat de precieze oorzaak in die regel (vorm, spatie, `bot`-voorvoegsel, 401 of webhook).
4. **Noodstop veilig testen.** Doe dit tussen twee rondes in, bijvoorbeeld om :30:
   - Stuur `/noodstop` en wacht op de bevestiging.
   - Stuur direct daarna `/hervat`.
   - Beide antwoorden komen binnen één Jarvis-run (maximaal 10 minuten).
   - Er gaat geen order verloren: KILL blokkeert alleen nieuwe orders. Posities blijven staan.

Daarnaast geldt:

- De koppeling met je chat blijft staan via het geheim `TELEGRAM_CHAT_ID`.
- `jarvis.json` (de offset) blijft bewaard, dus oude berichten worden niet opnieuw uitgevoerd.
- De berichten van vandaag 10:52 tot het herstel liggen nog bij Telegram (tot 24 uur). Jarvis beantwoordt ze bij de eerste geslaagde run. Heb je tussendoor `/noodstop` gestuurd, dan wordt die dan alsnog uitgevoerd.

## B. Privé-repo: toegang

**Wat vaststaat.**

- Controle-runs 1 (10:53, `jplh-state`) en 2 (14:33, `jplh-state-`) stopten bij "Privé-repo niet bereikbaar met STATE_TOKEN".
- Beide draaiden vóór de diagnose van PR #37. De HTTP-codes van die runs zijn dus niet bekend.
- Run 1 gebruikte een naam die niet bestaat.
- Voor run 2 is de oorzaak nog niet gemeten. Ik verzin er geen.

**Is de check correct voor een lege repo?** Ja, en nu ook bewezen met een test.

- `git ls-remote` op een lege repo geeft exitcode 0 met lege uitvoer. `--exit-code` gebruikt de check bewust níet, dus leeg wordt niet als onbereikbaar gezien.
- De nieuwe test `test_an_empty_private_repo_is_reported_as_reachable_not_as_an_error` maakt een echte lege bare repo. Uitkomst: `LEEG_OK`, lezen ja, schrijven ja, 0 branches. Er wordt niets geschreven.

**Nieuw: `jplh access-check --repo eigenaar/naam`.** Draait in de Voorwaarden-stap van "Stand verhuizen" en geeft één oorzaak:

| Oorzaak | Gemeten via | Wat te doen |
|---|---|---|
| `TOKEN_ONGELDIG` | `/user` geeft 401 | Token opnieuw plakken of opnieuw maken |
| `VERKEERDE_NAAM` | repo 404, maar een gelijkende repo is wél bereikbaar (die naam wordt getoond) | Doel-naam corrigeren |
| `NIET_GEKOPPELD` | repo 404, geen gelijkende repo | Bij de token onder "Only select repositories" de repo toevoegen |
| `RECHTEN` | repo zichtbaar, maar git-lezen of de schrijf-dry-run geweigerd | Contents op "Read and write" zetten (meer is niet nodig) |
| `NIET_PRIVE` | repo is publiek | Geweigerd |
| `LEEG_OK` | alles werkt, 0 branches | In orde, verwacht vóór de verhuizing |
| `OK` | alles werkt | In orde |

- Schrijven wordt getest met `git push --dry-run`. GitHub controleert dan de schrijfrechten, maar er komt niets in de repo.
- De tokenrechten blijven minimaal: Contents read/write en Metadata read.

**Volgende stap.** Draai de controle opnieuw met `reijmersp2006-png/jplh-state-` zodra deze PR is gemerged. De regel `oorzaak ...` in de log zegt dan precies wat er mis is.

## C. Onafhankelijke noodstop (ontwerp, nog niet actief)

**Werkflow `Noodstop`** (`.github/workflows/noodstop.yml`):

| Eis | Hoe |
|---|---|
| Werkt zonder Telegram | GitHub → Actions → Noodstop → Run workflow. Werkt ook vanuit de GitHub-app op je telefoon. |
| Persistente status | Zet het bestaande bestand `KILL` in de stand (publiek of privé, volgt `STATE_REPO`). Elke ronde neemt het over. |
| Geen nieuwe paper trades | `KILL` blokkeert in `risk.py` elke order. Dat is hetzelfde mechanisme als `/noodstop`. |
| Geen liquidatie | `KILL` blokkeert ook verkopen. Posities blijven staan. |
| Geen automatische hervatting | Niets haalt `KILL` weg, behalve `/hervat` of deze werkflow met `HERVAT`. |
| Expliciete bevestiging | Actie `hervat` weigert zonder het woord `HERVAT`. |
| Audit trail | Regel in `noodstop-log.jsonl` (tijd, actie, wie, reden, run, voor/na) plus een eigen git-commit. Het logboek zit in de vingerafdruk van `state-check`. |
| Geen gelijktijdigheid | `concurrency: paper`: wacht tot een lopende ronde klaar is (± 1 minuut) en draait nooit tegelijk met een verhuizing. |
| Alleen de eigenaar | `if: github.actor == github.repository_owner` |
| Zichtbaar in Command Center | "Noodstop aan/uit" stond er al (`state.kill`). De tekst noemt nu ook de werkflow. |
| Bevestiging | Na het pushen haalt de werkflow de stand opnieuw op en faalt als KILL er niet (of nog wel) staat. |
| Pauzes | Pauzes van afdelingen raakt de werkflow nooit. Een test bewijst dat de `data/`-boom bit-voor-bit gelijk blijft. |

**Automatisch pauzeren bij uitval van alle noodstopkanalen?** Mijn advies is voorlopig niet.

- Valt GitHub Actions uit, dan draait er ook geen ronde. Er wordt dan dus vanzelf niet gehandeld.
- De enige situatie waarin gehandeld wordt zonder werkend noodstopkanaal is "Telegram stuk, GitHub werkt". Dan werkt de werkflow-noodstop juist wel.
- Een automatische pauze zou bij een Telegram-storing de handel stilleggen zonder dat er risico is. Bij paper trading kost dat alleen leerdata.
- Voor 10.0 en zeker vóór echt geld stel ik een dodemansknop voor:
  - Telegram OFFLINE langer dan 6 uur: melding.
  - Langer dan 24 uur: alleen geen nieuwe posities (bestaande posities en stops blijven).
  - Opheffen alleen met de hand.
  - Dit verandert handelsgedrag, dus het komt pas na jouw akkoord.

## D. Gezondheidsmonitor

`jplh health` draait elke 10 minuten in Jarvis met `continue-on-error`. De stap faalt dus nooit en verandert niets.

| Onderdeel | HEALTHY | DEGRADED | OFFLINE | CRITICAL |
|---|---|---|---|---|
| Telegram API | getMe 200, geen webhook | netwerkfout of webhook actief | geen token, 401, 404 | n.v.t. |
| GitHub-authenticatie | werkflow-token geldig | API onbereikbaar | n.v.t. | token geweigerd |
| Privé-opslag | ingesteld, lezen+schrijven, branch aanwezig | nog niet in gebruik (publiek) | n.v.t. | ingesteld maar onbruikbaar |
| Handelsplanner | laatste ronde ≤ 75 min | ≤ 3 uur | n.v.t. | > 3 uur of geen ronde |
| Database-integriteit | alle `PRAGMA integrity_check` ok | n.v.t. | n.v.t. | corrupt of stand ontbreekt |
| Dashboardpublicatie | laatste deploy geslaagd, < 3 uur | mislukt of > 3 uur oud | geen deploy gevonden | n.v.t. |
| Noodstopkanalen | Telegram en werkflow | één kanaal | n.v.t. | geen enkel kanaal |
| AI Gateway | | | nog niet uitgerold (telt niet mee) | |

- Het totaal is de slechtste toestand van de onderdelen die meetellen.
- Fase 2 (na akkoord): `health.json` op het Command Center en een Telegram-melding bij een overgang naar CRITICAL.
- Bewaking van buitenaf (healthchecks.io of Cloudflare) blijft voorstel E uit 9.2 en wacht op jouw akkoord.

## E. Veiligheidsvoorwaarden

- Geen migratie.
- Geen branch verwijderd.
- Geen wijziging aan posities, geschiedenis, pauzes, strategie, risico of holdout.
- Live handelen blijft uit.
- Deze PR verandert geen handelsgedrag. Hij voegt toe:
  - twee diagnose-commando's;
  - een alleen-lezen gezondheidsstap;
  - een handmatige werkflow die pas iets doet als jij hem start.

## Uitvoering (24-11-2026, gemeten)

| Controle | Bron | Uitkomst |
|---|---|---|
| Telegram-token | Jarvis 45455330029 (18:03), stap Gezondheid | `HEALTHY token geldig, geen webhook` (was 404 tot 17:53) |
| getUpdates | Jarvis 45455330029 (18:03) | eenmalig `URLError` (netwerk); daarom nu 3 pogingen en de reden in de melding |
| getUpdates | Jarvis 45457172542 (18:13) | geslaagd; 0 wachtende berichten, offset ongewijzigd, "niets veranderd" |
| Chat-koppeling | config-check 18:13 | chat-id uit het geheim; niet meer in de stand; `connected` aanwezig |
| Health-monitor | 18:03 en 18:13 | totaal DEGRADED, alleen door "Privé-opslag nog niet in gebruik" (verwacht) |
| Stand | `state-check` op `paper-data` 85190db (17:45) | 26 bestanden, 6 databases ok, 19 journals / 84 regels, €904,13, pauzes crypto + metals, geen KILL |

**Gevonden en opgelost na PR #38:**

1. De noodstop zat in concurrency-groep `paper`. GitHub houdt per groep maar één wachtende run aan en annuleert de oudere, dus een door de wachter gestarte ronde kon een wachtende noodstop stil annuleren. De noodstop heeft nu een eigen groep.
2. Een ronde die al liep op het moment van de noodstop, handelde nog op de oude stand. De ronde leest KILL nu vlak vóór het handelen opnieuw uit de opgeslagen stand. Bij het bewaren zet git rebase de ronde bovenop de noodstop, zodat KILL blijft staan. Een test voert beide volgordes uit met de echte stappen uit `paper.yml` en `noodstop.yml`.
3. Telegram-netwerkfouten krijgen nu 3 pogingen. De melding noemt de reden (bijv. `timed out`) en nooit de token.
