"""Besturing: handelsmodus, noodstop en de poort naar live handelen.

- Modus A ``research``: alleen analyseren, voorstellen worden beoordeeld maar nooit uitgevoerd.
- Modus B ``paper``: nepgeld. De paper-bot van de holding handelt; NEXUS volgt.
- Modus C ``live``: bestaat in deze versie niet. ``set_mode("live")`` wordt altijd geweigerd
  en geeft de lijst van poortchecks terug die eerst moeten slagen.

De noodstop is hetzelfde ``KILL``-bestand dat de holding al gebruikt (``jplh kill``,
``/noodstop`` in Jarvis). NEXUS zet hem in de map van de holding en in zijn eigen opslag,
zodat beide stoppen. Aanzetten mag altijd en zonder token (veiligheid eerst); uitzetten
vraagt het admin-token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from nexus.db import Database


class Mode(str, Enum):
    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"


DEFAULT_MODE = Mode.PAPER


class LiveTradingDisabled(Exception):
    def __init__(self, gate: list[dict]) -> None:
        super().__init__("live handelen is uitgeschakeld")
        self.gate = gate


@dataclass
class Controls:
    db: Database
    holding_home: Path | None

    # ------------------------------------------------------------ modus
    def mode(self) -> Mode:
        raw = (self.db.get_state("mode") or {}).get("mode", DEFAULT_MODE.value)
        mode = Mode(raw)
        return Mode.PAPER if mode is Mode.LIVE else mode   # live kan nooit opgeslagen staan, maar voor de zekerheid

    def set_mode(self, mode: Mode, actor: str) -> Mode:
        if mode is Mode.LIVE:
            gate = self.live_gate()
            self.db.audit(actor, "mode_change_refused", {"requested": "live", "gate": gate})
            raise LiveTradingDisabled(gate)
        old = self.mode()
        self.db.set_state("mode", {"mode": mode.value})
        self.db.audit(actor, "mode_change", {"from": old.value, "to": mode.value})
        return mode

    def live_gate(self) -> list[dict]:
        """Alles wat waar moet zijn voordat live handelen zelfs maar aan kan. In deze versie
        slaagt de eerste check nooit: er is geen live broker-adapter gebouwd."""
        return [
            {"check": "live_broker_adapter", "passed": False,
             "detail": "er is nog geen live broker-adapter (fase 6)"},
            {"check": "expliciete_toestemming", "passed": False,
             "detail": "Phil moet live handelen apart en schriftelijk activeren"},
            {"check": "sleutels_zonder_opnamerecht", "passed": False,
             "detail": "geen exchange-sleutels gekoppeld; alleen sleutels zonder opname- en hefboomrecht zijn toegestaan"},
            {"check": "strategie_gevalideerd", "passed": False,
             "detail": "geen strategie heeft walk-forward, out-of-sample en paper-periode doorstaan"},
            {"check": "noodstop_getest", "passed": not self.kill_engaged(),
             "detail": "noodstop moet uit staan en getest zijn"},
        ]

    # ------------------------------------------------------------ noodstop
    def _kill_file(self) -> Path | None:
        return self.holding_home / "KILL" if self.holding_home else None

    def kill_engaged(self) -> bool:
        f = self._kill_file()
        return bool((self.db.get_state("kill") or {}).get("engaged")) or bool(f and f.exists())

    def kill_status(self) -> dict:
        state = self.db.get_state("kill") or {}
        f = self._kill_file()
        return {"engaged": self.kill_engaged(), "nexus": bool(state.get("engaged")),
                "holding_file": bool(f and f.exists()), "since": state.get("since"),
                "reason": state.get("reason")}

    def engage_kill(self, actor: str, reason: str) -> dict:
        now = datetime.now(tz=UTC).isoformat()
        self.db.set_state("kill", {"engaged": True, "since": now, "reason": reason})
        f = self._kill_file()
        if f is not None and f.parent.exists():
            f.write_text(f"noodstop via NEXUS {now}: {reason}\n", encoding="utf-8")
        self.db.audit(actor, "kill_engaged", {"reason": reason})
        return self.kill_status()

    def release_kill(self, actor: str, reason: str) -> dict:
        self.db.set_state("kill", {"engaged": False, "since": None, "reason": None})
        f = self._kill_file()
        if f is not None:
            f.unlink(missing_ok=True)
        self.db.audit(actor, "kill_released", {"reason": reason})
        return self.kill_status()
