# Plan JP-libau Holding

Het uitgebreide plan, met architectuur, het zelflerende systeem en het game-dashboard,
staat in het projectdocument "JP-libau Holding: plan voor een nieuwe start". Hieronder
de kern.

## Fasen

| Fase | Wanneer | Wat |
| --- | --- | --- |
| 1. Fundament | week 1-2 | repo, data voor alle markten, opslag, risico, boekhouding, logboek, tests |
| 2. Backtest-lab | week 2-3 | strategieën per afdeling testen met echte kosten, koop-en-houd als maatlat, walk-forward |
| 3. Paper 24/7 | week 3-4 | alle afdelingen draaien met nepgeld in de cloud (GitHub Actions) |
| 4. HQ-game | week 3-5 | dashboard in game-stijl, eerst één testscherm ter goedkeuring |
| 5. Leerlus | vanaf week 5 | strategietoernooi, herverdeling van nepkapitaal, weekrapport |
| Demofase | minimaal 3 maanden | daarna pas, met jouw akkoord, live met €100-200 |

## Hoe de bot veilig leert

1. Per afdeling draaien meerdere strategieën tegelijk met nepgeld, plus koop-en-houd als maatlat.
2. Na elke trade een nabespreking: verwachting, uitkomst, marktomstandigheden.
3. Elke week een beoordeling na kosten. Te weinig trades telt nog niet mee.
4. Nepkapitaal schuift langzaam naar wat werkt, met een maximum per strategie.
5. Instellingen veranderen alleen als ze ook beter werken op data die de bot nog niet zag.
6. Elke aanpassing krijgt een versienummer en komt in het weekrapport.

De risicogrenzen in `default_config.toml` vallen hier buiten: de leerlus kan ze niet aanpassen.

## Van papier naar echt geld

Een strategie mag pas live als hij minimaal 3 maanden en 50 trades op papier beter deed
dan koop-en-houd, binnen de risicogrenzen bleef, en de eigenaar er expliciet ja tegen zegt.
