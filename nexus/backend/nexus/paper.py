"""Paper trading van NEXUS: een eigen gesimuleerd account, los van de holding-bots en los van
echt geld. Er bestaat hier geen enkele verbinding met een broker.

Keten: voorstel → Risk Guardian (goedgekeurd) → order (idempotent: één order per voorstel)
→ simulatie-vulling tegen de laatste echte koers ± halve spread ± slippage, plus kosten
→ positie en kas bijwerken → waardering. Een order mag per ronde hooguit een klein deel van de
omzet van het laatste uur opnemen; de rest blijft openstaan (gedeeltelijke vulling) en wordt in
volgende rondes aangevuld. Bij een noodstop of een te oude koers gebeurt er niets.
Reconciliatie speelt alle vullingen opnieuw af en vergelijkt dat met de opgeslagen stand.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from jplh.config import HoldingConfig

from nexus.db import DEFAULT_ORG, Account, Database, Execution, Order, PortfolioValuation, PositionRow, iso, utcnow
from nexus.guardian import PortfolioView
from nexus.provenance import DataLabel

TRADABLE = (DataLabel.LIVE.value, DataLabel.DELAYED.value, DataLabel.SIMULATED.value)
OPEN = ("new", "partially_filled")
EPS = 1e-9


@dataclass(frozen=True)
class Quote:
    symbol: str
    price_eur: float | None
    ts: datetime | None
    label: str
    volume_eur: float | None = None      # omzet van de laatste periode in euro (None = onbekend)


QuoteFn = Callable[[str], Quote]


class PaperEngine:
    def __init__(self, db: Database, config: HoldingConfig, quote: QuoteFn, kill: Callable[[], bool],
                 participation: float = 0.01, spread_pct: float = 0.001, start_cash: float = 1000.0) -> None:
        self.db, self.config, self.quote, self.kill = db, config, quote, kill
        self.participation, self.spread_pct, self.start_cash = participation, spread_pct, start_cash

    # ── account ────────────────────────────────────────────────────────────────────────────
    def account_id(self, org_id: int = DEFAULT_ORG) -> int:
        with self.db.session.begin() as s:
            acc = s.scalar(select(Account).where(Account.org_id == org_id, Account.kind == "paper"))
            if acc is None:
                acc = Account(org_id=org_id, name="NEXUS Paper", kind="paper", starting_cash=self.start_cash,
                              cash=self.start_cash, peak_equity=self.start_cash)
                s.add(acc)
                s.flush()
            return acc.id

    def _cost(self, asset_class: str):
        return self.config.costs[asset_class]

    # ── orders ─────────────────────────────────────────────────────────────────────────────
    def submit(self, *, proposal_id: int, evaluation_id: int, key: str, symbol: str, asset_class: str, side: str,
               size_eur: float, org_id: int = DEFAULT_ORG) -> dict:
        """Maakt hooguit één order per voorstel (``client_order_id``). Tweede keer: dezelfde order terug."""
        acc_id = self.account_id(org_id)
        coid = f"nexus-{key}"
        with self.db.session.begin() as s:
            existing = s.scalar(select(Order).where(Order.client_order_id == coid))
            if existing is not None:
                return {"order_id": existing.id, "duplicate": True, "status": existing.status}
            if self.kill():
                raise PermissionError("noodstop staat aan")
            qty = None
            if side == "sell":
                pos = s.get(PositionRow, (acc_id, symbol))
                if pos is None or pos.quantity <= EPS:
                    raise ValueError("geen positie om te verkopen")
                q = self.quote(symbol)
                if q.price_eur is None:
                    raise ValueError("geen koers beschikbaar")
                qty = min(pos.quantity, size_eur / q.price_eur)
            o = Order(org_id=org_id, account_id=acc_id, proposal_id=proposal_id, evaluation_id=evaluation_id,
                      client_order_id=coid, symbol=symbol, asset_class=asset_class, side=side,
                      notional_eur=size_eur if side == "buy" else None, quantity=qty, status="new")
            s.add(o)
            s.flush()
            self.db.audit("paper", "order_created", {"order_id": o.id, "symbol": symbol, "side": side,
                                                     "size_eur": size_eur}, s=s, org_id=org_id)
            return {"order_id": o.id, "duplicate": False, "status": o.status}

    def step(self, now: datetime | None = None) -> list[dict]:
        """Eén simulatieronde voor alle open orders. Geeft de nieuwe vullingen terug."""
        now = now or utcnow()
        if self.kill():
            return []
        out = []
        with self.db.session.begin() as s:
            for o in s.scalars(select(Order).where(Order.status.in_(OPEN)).order_by(Order.id)).all():
                q = self.quote(o.symbol)
                if q.price_eur is None or q.label not in TRADABLE:
                    continue                                   # te oude of geen koers: wachten, niet gokken
                fill = self._fill(s, o, q, now)
                if fill:
                    out.append(fill)
        return out

    def _fill(self, s, o: Order, q: Quote, now: datetime) -> dict | None:
        acc = s.get(Account, o.account_id)
        cost = self._cost(o.asset_class)
        half = self.spread_pct / 2
        cap = q.volume_eur * self.participation if q.volume_eur else None
        first = o.filled_quantity <= EPS
        min_fee = cost.min_fee_eur if first else 0.0
        if o.side == "buy":
            remaining = o.notional_eur - o.filled_notional_eur
            budget = min(remaining, cap) if cap else remaining
            budget = min(budget, acc.cash)
            px = q.price_eur * (1 + half + cost.slippage_pct)
            fee = max(min_fee, budget * cost.fee_pct)
            if budget <= fee + EPS:
                if acc.cash <= fee + EPS:
                    o.status, o.reject_reason = "rejected", "onvoldoende kas"
                return None
            qty = (budget - fee) / px
            acc.cash -= budget
            o.filled_notional_eur += budget
            pos = s.get(PositionRow, (acc.id, o.symbol))
            if pos is None:
                s.add(PositionRow(account_id=acc.id, symbol=o.symbol, asset_class=o.asset_class, quantity=qty,
                                  avg_price_eur=px, updated_at=now))
            else:
                pos.avg_price_eur = (pos.quantity * pos.avg_price_eur + qty * px) / (pos.quantity + qty)
                pos.quantity += qty
                pos.updated_at = now
            done = o.filled_notional_eur >= o.notional_eur * (1 - 1e-6)
        else:
            pos = s.get(PositionRow, (acc.id, o.symbol))
            held = pos.quantity if pos else 0.0
            remaining = min(o.quantity - o.filled_quantity, held)
            if remaining <= EPS:
                o.status, o.reject_reason = "rejected", "positie is er niet meer"
                return None
            px = q.price_eur * (1 - half - cost.slippage_pct)
            qty = min(remaining, cap / q.price_eur) if cap else remaining
            gross = qty * px
            fee = max(min_fee, gross * cost.fee_pct)
            acc.cash += gross - fee
            acc.realized_pnl += qty * (px - pos.avg_price_eur) - fee
            pos.quantity -= qty
            pos.updated_at = now
            if pos.quantity <= EPS * max(1.0, held):
                s.delete(pos)
            o.filled_notional_eur += gross
            done = o.filled_quantity + qty >= o.quantity * (1 - 1e-6)
        acc.fees += fee
        o.filled_quantity += qty
        o.status = "filled" if done else "partially_filled"
        o.updated_at = now
        s.add(Execution(order_id=o.id, account_id=acc.id, ts=now, symbol=o.symbol, side=o.side, quantity=qty,
                        price_eur=px, reference_price_eur=q.price_eur, fee_eur=fee, data_label=q.label))
        self.db.audit("paper", "fill", {"order_id": o.id, "symbol": o.symbol, "side": o.side, "quantity": qty,
                                        "price_eur": px, "fee_eur": fee, "status": o.status}, s=s, org_id=o.org_id)
        return {"order_id": o.id, "symbol": o.symbol, "side": o.side, "quantity": qty, "price_eur": px,
                "fee_eur": fee, "status": o.status}

    def cancel(self, order_id: int) -> str:
        with self.db.session.begin() as s:
            o = s.get(Order, order_id)
            if o is None:
                raise KeyError("onbekende order")
            if o.status in OPEN:
                o.status, o.updated_at = "cancelled", utcnow()
                self.db.audit("paper", "order_cancelled", {"order_id": o.id}, s=s, org_id=o.org_id)
            return o.status

    # ── waardering en reconciliatie ────────────────────────────────────────────────────────
    def valuation(self, org_id: int = DEFAULT_ORG, now: datetime | None = None, record: bool = False) -> dict:
        now = now or utcnow()
        acc_id = self.account_id(org_id)
        with self.db.session.begin() as s:
            acc = s.get(Account, acc_id)
            positions, value, unknown = [], 0.0, []
            for p in s.scalars(select(PositionRow).where(PositionRow.account_id == acc_id)).all():
                q = self.quote(p.symbol)
                px = q.price_eur
                if px is None:
                    unknown.append(p.symbol)
                v = p.quantity * (px if px is not None else p.avg_price_eur)
                value += v
                positions.append({"symbol": p.symbol, "asset_class": p.asset_class, "quantity": p.quantity,
                                  "avg_price_eur": p.avg_price_eur, "price_eur": px, "price_label": q.label,
                                  "value_eur": v, "unrealized_eur": p.quantity * (px - p.avg_price_eur) if px else None})
            equity = acc.cash + value
            acc.peak_equity = max(acc.peak_equity, equity)
            day_ago = s.scalar(select(PortfolioValuation).where(
                PortfolioValuation.account_id == acc_id, PortfolioValuation.ts <= now - timedelta(hours=24))
                .order_by(PortfolioValuation.ts.desc()).limit(1))
            day_start = day_ago.equity_eur if day_ago else acc.starting_cash
            if record:
                s.merge(PortfolioValuation(account_id=acc_id, ts=now.replace(second=0, microsecond=0),
                                           equity_eur=equity, cash_eur=acc.cash, label=DataLabel.SIMULATED.value))
            curve = [[iso(v.ts), v.equity_eur] for v in s.scalars(
                select(PortfolioValuation).where(PortfolioValuation.account_id == acc_id)
                .order_by(PortfolioValuation.ts)).all()]
            return {"account_id": acc_id, "label": DataLabel.SIMULATED.value, "starting_cash": acc.starting_cash,
                    "cash_eur": acc.cash, "positions_value_eur": value, "equity_eur": equity,
                    "pnl_eur": equity - acc.starting_cash, "realized_eur": acc.realized_pnl, "fees_eur": acc.fees,
                    "unrealized_eur": sum(p["unrealized_eur"] or 0 for p in positions),
                    "peak_eur": acc.peak_equity, "drawdown": 1 - equity / acc.peak_equity if acc.peak_equity else 0.0,
                    "day_pnl_pct": equity / day_start - 1 if day_start else 0.0, "positions": positions,
                    "unpriced": unknown, "equity_curve": curve}

    def view(self, org_id: int = DEFAULT_ORG) -> PortfolioView:
        v = self.valuation(org_id)
        pv, cls = {}, {}
        for p in v["positions"]:
            pv[p["symbol"]] = p["value_eur"]
            cls[p["asset_class"]] = cls.get(p["asset_class"], 0.0) + p["value_eur"]
        return PortfolioView(v["equity_eur"], pv, cls, v["day_pnl_pct"], v["drawdown"])

    def reconcile(self, org_id: int = DEFAULT_ORG) -> dict:
        """Speel alle vullingen opnieuw af vanaf de startkas en vergelijk met de opgeslagen stand."""
        acc_id = self.account_id(org_id)
        with self.db.session() as s:
            acc = s.get(Account, acc_id)
            cash, realized, fees = acc.starting_cash, 0.0, 0.0
            pos: dict[str, list[float]] = {}
            for e in s.scalars(select(Execution).where(Execution.account_id == acc_id).order_by(Execution.id)).all():
                q, avg = pos.get(e.symbol, [0.0, 0.0])
                if e.side == "buy":
                    cash -= e.quantity * e.price_eur + e.fee_eur
                    pos[e.symbol] = [q + e.quantity, (q * avg + e.quantity * e.price_eur) / (q + e.quantity)]
                else:
                    cash += e.quantity * e.price_eur - e.fee_eur
                    realized += e.quantity * (e.price_eur - avg) - e.fee_eur
                    pos[e.symbol] = [q - e.quantity, avg]
                fees += e.fee_eur
            stored = {p.symbol: p.quantity for p in s.scalars(select(PositionRow).where(PositionRow.account_id == acc_id))}
            diffs = []
            tol = 1e-6
            if abs(cash - acc.cash) > tol:
                diffs.append(f"kas: opgeslagen {acc.cash:.6f}, opnieuw berekend {cash:.6f}")
            if abs(realized - acc.realized_pnl) > tol:
                diffs.append(f"gerealiseerd: {acc.realized_pnl:.6f} tegen {realized:.6f}")
            if abs(fees - acc.fees) > tol:
                diffs.append(f"kosten: {acc.fees:.6f} tegen {fees:.6f}")
            for sym in set(stored) | {k for k, v in pos.items() if v[0] > EPS}:
                a, b = stored.get(sym, 0.0), pos.get(sym, [0.0])[0]
                if abs(a - b) > tol * max(1.0, abs(b)):
                    diffs.append(f"{sym}: opgeslagen {a}, opnieuw berekend {b}")
            return {"ok": not diffs, "differences": diffs, "checked_at": utcnow().isoformat()}

    def orders(self, org_id: int = DEFAULT_ORG, limit: int = 50) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(Order).where(Order.org_id == org_id).order_by(Order.id.desc()).limit(limit)).all()
            return [{"id": o.id, "client_order_id": o.client_order_id, "proposal_id": o.proposal_id, "symbol": o.symbol,
                     "side": o.side, "notional_eur": o.notional_eur, "quantity": o.quantity,
                     "filled_quantity": o.filled_quantity, "filled_notional_eur": o.filled_notional_eur,
                     "status": o.status, "reject_reason": o.reject_reason, "created_at": iso(o.created_at),
                     "updated_at": iso(o.updated_at)} for o in rows]

    def executions(self, org_id: int = DEFAULT_ORG, limit: int = 100) -> list[dict]:
        acc_id = self.account_id(org_id)
        with self.db.session() as s:
            rows = s.scalars(select(Execution).where(Execution.account_id == acc_id)
                             .order_by(Execution.id.desc()).limit(limit)).all()
            return [{"id": e.id, "order_id": e.order_id, "ts": iso(e.ts), "symbol": e.symbol, "side": e.side,
                     "quantity": e.quantity, "price_eur": e.price_eur, "reference_price_eur": e.reference_price_eur,
                     "slippage_bps": (e.price_eur / e.reference_price_eur - 1) * 1e4, "fee_eur": e.fee_eur,
                     "data_label": e.data_label} for e in rows]


def quote_from_store(market_path, config: HoldingConfig, demo: bool, now_fn=lambda: datetime.now(tz=UTC)) -> QuoteFn:
    """Laatste uurkoers uit de koersdatabase van de holding, omgerekend naar euro."""
    from jplh.prices import PriceBook, PriceError
    from jplh.store import Store

    from nexus.provenance import market_label

    def quote(symbol: str) -> Quote:
        if market_path is None or not market_path.exists():
            return Quote(symbol, None, None, DataLabel.UNAVAILABLE.value)
        st = Store(market_path)
        try:
            insts = {i.symbol: i for i in config.instruments}
            if symbol not in insts:
                return Quote(symbol, None, None, DataLabel.UNAVAILABLE.value)
            book = PriceBook(insts)
            for i in config.instruments:
                last = st.latest_close(i.symbol, "1h")
                if last:
                    book.update(i.symbol, *last)
            try:
                px = book.price_eur(symbol)
            except PriceError:
                return Quote(symbol, None, None, DataLabel.UNAVAILABLE.value)
            ts = book.ts(symbol)
            bars = st.candles(symbol, "1h", limit=1)
            vol = bars[-1].volume * px if bars and bars[-1].volume > 0 else None
            if demo:
                label = DataLabel.SIMULATED
            else:
                label = market_label(ts, now_fn(), timedelta(hours=config.risk.max_data_age_hours))
            return Quote(symbol, px, ts, label.value, vol)
        finally:
            st.close()

    return quote
