# Audit: Trend met volatiliteitsfilter v1 op IWDA.AS

Data 2020-12-30 t/m 2026-11-11 (1503 dagen, vingerafdruk `8a0c442447c354d4`). Out-of-sample vanaf 2025-06-04. Parameters `{'fast': 50, 'slow': 200, 'vol_window': 20, 'lookback': 252}` ongewijzigd (versie 1).

## Oorspronkelijke uitkomst (bewaard, niet aangepast)

| Out-of-sample | Strategie | Koop-en-houd |
|---|---|---|
| Totaal rendement | +7,2% | +30,3% |
| Rendement per jaar | +4,9% | +19,8% |
| Maximale daling | 5,1% | 6,5% |
| Sharpe (95%-interval) | 0,65 [-0,97; 2,27] | 1,72 [0,09; 3,34] |
| Sortino | 0,96 | 2,57 |
| Profit factor | 2,48 | n.v.t. |
| Win rate | 67% | n.v.t. |
| Verwachting per trade | €6,03 | n.v.t. |
| Tijd in de markt | 55% | 100% |
| Rendement per jaar / tijd in markt | +8,9% | +19,8% |
| Transactiekosten | €55,25 | €2,25 |
| Trades (gesloten) | 12 | 1 aankoop |

Verschil met koop-en-houd: -23,1% totaal; per jaar -14,9% (90%-interval -25,7% tot -5,6%). Probabilistische Sharpe 78%, gedefleerd voor 9 pogingen 61% (drempel 95%).

## Attributie (log-rendement, out-of-sample)

| Onderdeel | Log-procentpunt |
|---|---|
| buiten de markt | -14,96 |
| kosten | -5,25 |
| wisseldagen (instap/uitstap op de opening) | 0,70 |
| in de markt (zelfde als maatlat) | -0,00 |
| **Totaal verschil** | **-19,51** |

## Bevindingen

- Buiten de markt: de strategie zat 45% van de tijd niet in de markt. Dat kostte 15,0 van de 19,5 log-procentpunt achterstand.
  - oorzaak 'beweeglijkheid boven mediaan': -10,7 log-procentpunt
  - oorzaak 'trend omlaag': -4,2 log-procentpunt
  - in bear-regime (23 dagen): -6,5 log-procentpunt (gemiste stijging)
  - in bull-regime (131 dagen): -8,4 log-procentpunt (gemiste stijging)
- Kosten: 5,3 log-procentpunt; €55,25 op €1000 kapitaal, €4,50 per heen-en-terug. Zonder kosten +13,0%, met €10.000 kapitaal +9,0%.
- Heen-en-weer: 5 van 12 trades duurden ≤3 dagen, samen €-13,88 resultaat na €23,01 kosten.
- Herinstap: gemiddeld 8,8 dagen buiten de markt en +1,10% duurder terug in dan uitgestapt.
- Uitstappen vóór een stijging van >3% binnen 20 dagen: 0.
- Risico: maximale daling 5,1% tegen 6,5% (1,4 pt minder) voor 23,1 pt minder rendement. Calmar 0,96 tegen 3,07.
- Periode: koop-en-houd haalde out-of-sample +20,2% per jaar (volatiliteit 11%), in-sample +8,4%, over alle data +14,1%. 94% van de out-of-sample dagen was bull-regime.
- Ook over de hele periode achter: +5,2% tegen +72,4%, dus niet alleen pech met de testperiode.
- Onzekerheid: verschil per jaar -14,9%, 90%-interval -25,7% tot -5,6%; kans dat de strategie per jaar beter was: 0,8%.
- Parameters: 9 buren getest. In-sample beste {'fast': 50, 'slow': 200, 'vol_window': 20, 'lookback': 504} haalde out-of-sample Sharpe 0,56; de hele rij lag out-of-sample tussen -0,06 en 0,73, tegen 1,72 voor koop-en-houd. De originele instelling had in-sample een Sharpe van -0,07.
- Look-ahead: 40 besluitmomenten herberekend op afgekapte data, 0 verschillen.
- Data: 1503 dagkoersen, 0 ongeldig, 0 sprongen >10%, 7 gaten >4 dagen (feestdagen), vingerafdruk 8a0c442447c354d4.

## Aannames

- Uitvoering: besluit op slotkoers, uitvoering op de volgende opening.
- Kosten: fee 0,05% (minimaal €1,25), slippage 0,05%, spread 0,10%.
- Niet gemodelleerd: feestdagen (gaten in de reeks, geen handel), survivorship: universum is de huidige instrumentenlijst, belasting.
