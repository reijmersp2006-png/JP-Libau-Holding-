# Beveiliging, compliance en incidenten

## Nu geregeld
| Maatregel | Waar |
|---|---|
| Geen live handel mogelijk; live-poort weigert altijd | `nexus/controls.py` |
| Geen order zonder goedgekeurd Risk-Guardian-oordeel (ook in de database: `orders.evaluation_id` verplicht) | `app.py`, `db.py` |
| LLM's kunnen geen orders plaatsen: er is geen pad van AI-output naar `PaperEngine.submit` buiten een goedgekeurd voorstel | `app.py` |
| Tenant-scheiding: `org_id` op alle klantdata, queries filteren erop | `db.py`, tests `test_db.py` |
| Live account vereist een broker-koppeling (database-constraint) | `db.py` |
| Admin-token met constante-tijd-vergelijking; zonder token uitgeschakeld | `app.py` |
| Rate-limit op schrijvende endpoints, invoervalidatie met Pydantic | `app.py`, `proposals.py` |
| CORS en WebSocket-origin alleen voor de eigen frontend | `app.py` |
| Audit-log alleen toevoegen | `db.py` |
| Geen sleutels in frontend of repo | `.gitignore`, `.env.example` |

## Nog te doen vóór klanten
- Echte authenticatie (wachtwoord-hash met argon2, sessies, wachtwoordherstel, optionele MFA/TOTP) en rollen per organisatie.
- Versleuteling van broker-gegevens in een secret store (KMS/Vault).
- Afhankelijkheden scannen (Dependabot / `pip-audit` / `npm audit`) en security-tests in CI.
- Wallet-integratie via signing in de wallet van de gebruiker (WalletConnect), nooit opgeslagen private keys.
- Juridische toets MiFID II, MiCA, AFM en AVG. Tot die klaar is blijven klantfuncties uit (`customer_features_enabled: false`).

## Incidentrespons
1. **Stoppen**: noodstop aan (knop, API of `/noodstop` in Jarvis). Dit blokkeert elke order, ook verkopen.
2. **Vastleggen**: audit-log en JSON-logs veiligstellen; tijdlijn noteren.
3. **Beperken**: gelekte sleutels intrekken bij de exchange; admin-token roteren; getroffen accounts bevriezen.
4. **Herstellen**: reconciliatie draaien (`GET /api/paper`), posities met de broker vergelijken, pas daarna noodstop uit (admin-token).
5. **Melden**: bij persoonsgegevens binnen 72 uur bij de Autoriteit Persoonsgegevens; betrokkenen informeren waar nodig.
6. **Leren**: oorzaak, fix en test vastleggen; een regressietest toevoegen.
