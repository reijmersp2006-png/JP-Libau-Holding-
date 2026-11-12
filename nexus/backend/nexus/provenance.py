"""Herkomst van data. Elke waarde die NEXUS toont krijgt precies één label.

- LIVE: streaming koers, minder dan een minuut oud. NEXUS heeft nog geen streaming bron,
  dus dit label komt in deze versie niet voor (en wordt ook niet nagebootst).
- DELAYED: echte koers van een bron die per uur ververst en binnen de versheidsgrens valt.
- HISTORICAL: echte koers, maar ouder dan de versheidsgrens.
- SIMULATED: paper trading of demo. Echt berekend, maar geen echt geld of nep-koersen.
- UNAVAILABLE: er is geen data. Er wordt dan ook geen getal getoond.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum


class DataLabel(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    HISTORICAL = "HISTORICAL"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


LIVE_WINDOW = timedelta(minutes=1)


def market_label(ts: datetime | None, now: datetime, max_age: timedelta, *, streaming: bool = False,
                 demo: bool = False) -> DataLabel:
    """Label voor een marktkoers met tijdstip ``ts`` (begin van de laatste candle)."""
    if ts is None:
        return DataLabel.UNAVAILABLE
    if demo:
        return DataLabel.SIMULATED
    age = now - ts
    if streaming and age <= LIVE_WINDOW:
        return DataLabel.LIVE
    if age <= max_age:
        return DataLabel.DELAYED
    return DataLabel.HISTORICAL


def labeled(value, label: DataLabel, **extra) -> dict:
    """Een waarde met label. Bij UNAVAILABLE wordt de waarde altijd weggelaten."""
    out = {"value": None if label is DataLabel.UNAVAILABLE else value, "label": label.value}
    out.update(extra)
    return out
