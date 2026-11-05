"""Officiële ECB-referentiekoersen (dagelijks, rond 16:00 CET). Controlebron voor valuta.

Endpoint: ``GET https://data-api.ecb.europa.eu/service/data/EXR/D.{CUR}.EUR.SP00.A?format=csvdata``
Waarde = hoeveel {CUR} je krijgt voor 1 euro.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from jplh.data.http import get

BASE_URL = "https://data-api.ecb.europa.eu/service/data/EXR"


def parse_csv(text: str) -> list[tuple[date, float]]:
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        value = row.get("OBS_VALUE")
        if value:
            rows.append((date.fromisoformat(row["TIME_PERIOD"]), float(value)))
    return sorted(rows)


class ECB:
    name = "ecb"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def rates(self, currency: str, last: int = 30) -> list[tuple[date, float]]:
        url = f"{self.base_url}/D.{currency}.EUR.SP00.A?lastNObservations={last}&format=csvdata"
        return parse_csv(get(url).decode("utf-8"))

    def ping(self) -> str:
        rows = self.rates("USD", 1)
        return f"EUR/USD {rows[-1][1]:.4f} op {rows[-1][0]}" if rows else "geen koers"
