"""Brug naar de JP-libau Holding (``jplh``). NEXUS rekent niets opnieuw uit wat de holding al
doet: het opent dezelfde databases, laat ``jplh.site.build_state`` de stand opbouwen en voegt
daar alleen herkomstlabels en een paar afgeleide getallen aan toe. Alleen lezen."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jplh.config import HoldingConfig, load_config
from jplh.desks import open_desks
from jplh.models import Side
from jplh.prices import PriceError
from jplh.site import build_state
from jplh.store import Store

from nexus.guardian import PortfolioView
from nexus.provenance import DataLabel, market_label
from nexus.settings import Settings


@dataclass
class Snapshot:
    now: datetime
    demo: bool
    home: Path
    config: HoldingConfig
    state: dict                                   # zoals het HQ-dashboard hem ook krijgt
    positions: list[dict] = field(default_factory=list)
    quotes: dict[str, dict] = field(default_factory=dict)   # symbool -> prijs, ts, label
    realized_eur: float = 0.0
    unrealized_eur: float = 0.0
    buy_fees_eur: float = 0.0
    fees_eur: float = 0.0
    cash_eur: float = 0.0
    fills_today: int = 0
    last_fill: str | None = None
    radar_at: str | None = None

    @property
    def max_age(self) -> timedelta:
        return timedelta(hours=self.config.risk.max_data_age_hours)

    def portfolio_view(self) -> PortfolioView:
        t = self.state["total"]
        pv: dict[str, float] = {}
        classes: dict[str, float] = {}
        for p in self.positions:
            pv[p["symbol"]] = pv.get(p["symbol"], 0.0) + p["value_eur"]
            classes[p["desk"]] = classes.get(p["desk"], 0.0) + p["value_eur"]
        paused = any(d.get("paused_reason") for d in self.state["desks"])
        return PortfolioView(t["equity_eur"], pv, classes, t["day_pnl_pct"], t["drawdown"], paused)


class HoldingBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._cache: tuple[float, Snapshot | None] | None = None
        self._config = load_config(settings.holding_config)

    @property
    def config(self) -> HoldingConfig:
        return self._config

    def home(self) -> Path | None:
        if self.settings.demo:
            return self._ensure_demo()
        h = self.settings.holding_home
        if h is not None and (h / "data" / "holding.sqlite3").exists():
            return h
        return None

    def _ensure_demo(self) -> Path:
        from jplh.paper import build_demo
        home = self.settings.demo_home
        if not (home / "data" / "holding.sqlite3").exists():
            build_demo(self._config, home, hours=48, history_days=20)
        return home

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def snapshot(self) -> Snapshot | None:
        with self._lock:
            if self._cache and time.monotonic() - self._cache[0] < self.settings.cache_seconds:
                return self._cache[1]
            snap = self._build()
            self._cache = (time.monotonic(), snap)
            return snap

    def _build(self, now: datetime | None = None) -> Snapshot | None:
        home = self.home()
        if home is None:
            return None
        demo = self.settings.demo
        cfg = self._config
        market = Store(home / "data" / "holding.sqlite3")
        desks = open_desks(cfg, home, market)
        try:
            if demo:
                # De demo-wereld heeft een eigen klok: de laatste nep-koers.
                last = market.db.execute("SELECT MAX(ts) FROM candles WHERE interval='1h'").fetchone()[0]
                now = datetime.fromisoformat(last) + timedelta(hours=1) if last else datetime.now(tz=UTC)
            now = now or datetime.now(tz=UTC)
            state = build_state(cfg, desks, market, home, now, demo=demo)
            snap = Snapshot(now=now, demo=demo, home=home, config=cfg, state=state)
            max_age = snap.max_age
            today = now.date()
            for cls, desk in desks.items():
                h = desk.holding
                prices = h.prices(now)
                pf = h.portfolio
                snap.realized_eur += pf.realized_pnl_eur
                snap.fees_eur += pf.fees_eur
                snap.cash_eur += pf.cash_eur
                fills = h.store.fills()
                snap.buy_fees_eur += sum(f.fee_eur for f in fills if f.side is Side.BUY)
                snap.fills_today += h.store.fills_on(today)
                if fills:
                    ts = fills[-1].ts.isoformat()
                    snap.last_fill = max(snap.last_fill or ts, ts)
                for inst in desk.instruments:
                    ts = prices.ts(inst.symbol)
                    try:
                        px = prices.price_eur(inst.symbol)
                    except PriceError:
                        px = None
                    label = market_label(ts if px is not None else None, now, max_age, demo=demo)
                    snap.quotes[inst.symbol] = {"symbol": inst.symbol, "desk": cls, "price_eur": px,
                                                "ts": ts.isoformat() if ts else None, "label": label.value,
                                                "source": inst.source}
                sel = desk.selection()
                for sym, pos in pf.positions.items():
                    q = snap.quotes.get(sym, {})
                    px = q.get("price_eur")
                    value = pos.quantity * (px if px is not None else pos.avg_price_eur)
                    unreal = pos.quantity * (px - pos.avg_price_eur) if px is not None else None
                    if unreal is not None:
                        snap.unrealized_eur += unreal
                    snap.positions.append({
                        "symbol": sym, "desk": cls, "quantity": pos.quantity, "avg_eur": pos.avg_price_eur,
                        "price_eur": px, "value_eur": value, "unrealized_eur": unreal,
                        "pnl_pct": (px / pos.avg_price_eur - 1) if px is not None else None,
                        "strategy": sel.get(sym, ""), "price_label": q.get("label", DataLabel.UNAVAILABLE.value),
                        "price_ts": q.get("ts")})
            row = market.db.execute("SELECT MAX(fetched_at) FROM radar").fetchone()
            snap.radar_at = row[0] if row else None
            snap.positions.sort(key=lambda p: -p["value_eur"])
            return snap
        finally:
            for d in desks.values():
                d.holding.store.close()
            market.close()
