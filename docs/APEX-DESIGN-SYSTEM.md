# APEX · Design system (D2)

Eén systeem, gebouwd op design 4.1. Tokens staan in `nexus/web/app/globals.css`. Componenten staan in
`nexus/web/components/ds.tsx` (nieuw) en `components/ui.tsx` (bestaand).

## Principes

1. **Data eerst.** Elk getal heeft een herkomstlabel. Een leeg scherm zegt waarom het leeg is.
2. **Eén accent.** IJsblauw (`--ice`) betekent selectie, focus of de actieve reeks. Groen en rood zijn voor richting (stijgen of dalen), nooit voor decoratie.
3. **Rust.** Beweging alleen om een verandering uit te leggen. Bij `prefers-reduced-motion` staat alles stil.
4. **Gemeten, regel, AI en mens zijn altijd te onderscheiden** via `Provenance`.

## Tokens

| Token | Waarde | Gebruik | Contrast op paneel (#0F1217) |
|---|---|---|---|
| `--bg` | #07080B | pagina | — |
| `--surface-0/1/2/3` | #0B0D11 / #0F1217 / #13171D / #181C23 | zijbalk / paneel / verhoogd / hover en selectie | — |
| `--text-1` | #F4F6FA | cijfers, titels | 17,3:1 |
| `--text-2` | #D9DEE7 | lopende tekst | 13,9:1 |
| `--text-3` (slate-400) | #8B94A3 | labels | 6,1:1 |
| `--text-4` (slate-500) | #7E8798 | bijschrift, as-labels | 5,2:1 (was 4,0:1) |
| slate-600 | #788192 | zachtste tekst | 4,8:1 (was 2,3:1) |
| `--metal` | #B9C2CF | primaire reeks (vermogen, koers) | 10,4:1 |
| `--ice` | #8CCBF2 | accent, focus | 10,7:1 |
| `--series-2` | #A79BEA | tweede reeks, vergelijking | 7,6:1 |
| `--series-3` | #DDB25C | derde reeks, waarschuwing | 9,5:1 |
| `--sim` | #BEB4F0 | gesimuleerd / fixture | 9,8:1 |
| up / down | #4CC495 / #E25A64 | richting | 8,6:1 / 5,3:1 |
| `--dur-1/2/3` | 140 / 240 / 420 ms | hover-focus / paneel-tab / binnenkomst | — |

## Typografie

Geist Sans voor tekst en Geist Mono voor codes en sporen. Cijfers gebruiken `tabular-nums` (`.num`).

| Klasse | Grootte | Gebruik |
|---|---|---|
| `.t-display` | 40 px, semibold | één hoofdmaat per scherm (vermogen, koers) |
| `.t-kpi` | 20 px | kerncijfer in een strip |
| `.title-lg` / `.title-md` | 28 / 15 px | paginatitel / paneeltitel |
| `.t-label` | 11,5 px | label boven een cijfer |
| `.t-micro` | 10,5 px | bijschrift, bron, tijd |

## Ruimte en grid

* Basis 4 px. Panelen hebben 20 px binnenruimte. Grids hebben 20 px tussenruimte (`gap-5`).
* Breekpunten: mobiel < 640, tablet 640–1279, desktop ≥ 1280 (`xl`), breed ≥ 1760 (workstation met drie kolommen).
* Elk grid-item heeft `min-w-0` (zit nu in `Panel`), zodat tabellen binnen hun paneel scrollen en niet de pagina oprekken.

## Componenten (`ds.tsx`)

| Component | Doel |
|---|---|
| `PageHeader` | eyebrow, titel, uitleg, metaregel (versheid), rechterzijde (status) |
| `KpiStrip` / `KpiCell` | strip met kerncijfers. `wide` maakt de hoofdmaat; `label2` toont het herkomstlabel; `href` maakt de cel klikbaar |
| `Freshness` | label en tijd, bijvoorbeeld "Vertraagd · 11 nov · 3 dagen geleden". DELAYED wordt nooit als live getoond |
| `Provenance` | gemeten / AI-mening / vaste regel / mens / gesimuleerd |
| `Delta` | procentverandering met richting-kleur en teken |
| `Tick` | korte oplichting wanneer een waarde verandert (uit bij reduced motion) |
| `Drawer` | zijpaneel: Esc sluit, focus gaat erin, `aria-modal` |
| `Tabs` | `role="tablist"`, `aria-selected`, loopt op smalle schermen door op een nieuwe regel |
| `Unavailable` | lijst "wat ontbreekt en waarom" |
| `CHART` | kleuren voor Lightweight Charts |

Bestaand en hergebruikt: `Panel`, `PageTitle`, `StatusDot`, `TruthTag`, `DataBadge`, `Empty`, `Skeleton`, `Segmented`, `Btn`, `useAdmin`.

## Grafieken

* **Koers:** Lightweight Charts v5 (`PriceChart`): candles of lijn, volume op een eigen schaal, SMA 20/50/200, RSI 14 in een eigen paneel (verhouding 3:1), vergelijking in % vanaf het eerste punt, markeringen (amber N = nieuws, violet sim = gesimuleerd). De TradingView-attributie blijft staan, zoals de licentie vraagt.
* **Vermogen:** `EquityChart`: metaal-lijn met vlak, drawdown in rood eronder, stippellijn voor het startkapitaal.
* **Analyse:** eigen SVG (heatmap, correlatiematrix, Arena-staven, Neural Core). Er is geen extra bibliotheek nodig (zie de tool-evaluatie).
* **Assen** in `--text-4`. Rasterlijnen op 5% wit. Kruisdraad neutraal grijs.

## Tabellen (`.dtable`)

Kop klein en grijs. Cijfers rechts uitgelijnd (`.r`) en tabulair. Een rij licht op bij hover. Een geselecteerde rij heeft `aria-selected` en een lichte achtergrond. Op mobiel scrollt de tabel binnen het paneel.

## Toestanden

| Toestand | Weergave |
|---|---|
| laden | `Skeleton` met de vorm van de inhoud |
| leeg | `Empty` met de reden ("geen X-verbinding", "nog geen Council-run") |
| niet verbonden | `TruthTag unavailable` plus de reden, nooit nul als waarde |
| fout | paneel met de foutmelding van de API |
| gesimuleerd | violet `DataBadge SIMULATED`, stippellijnen in grafieken |
| hover, focus | `--dur-1`, focusring in `--ice` |
| actief | `aria-pressed` / `aria-selected` met `--surface-3` |

## Beweging

`.page-in` (binnenkomst, 420 ms), `.tick` (waarde verandert, 1,2 s), opacity-overgangen in de Neural Core (240 ms).
Alle animaties staan in de `prefers-reduced-motion`-lijst en gaan daar uit.

## Toegankelijkheid

* Contrast: alle tekstkleuren ≥ 4,5:1 op paneel (zie tabel).
* Toetsenbord: knopen in de Neural Core zijn `role="button"` met Enter/Spatie. De Drawer sluit met Esc.
* Elk netwerk of elke grafiek heeft een tekstalternatief: de Neural Core heeft een Lijst-weergave, de grafiek heeft `role="img"` met een label, en de statistieken staan ernaast als tekst.
* Taal: `lang="nl"` met `hyphens-auto` voor lange Nederlandse woorden in smalle kaarten.
