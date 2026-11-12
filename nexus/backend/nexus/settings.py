"""Instellingen uit omgevingsvariabelen. Geheimen worden nooit teruggegeven aan de frontend:
van een sleutel melden we alleen of hij aanwezig is."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass(frozen=True)
class Settings:
    holding_home: Path | None = None        # map met data/holding.sqlite3 van de holding (bijv. de paper-data branch)
    holding_config: Path | None = None      # optioneel: config/holding.toml
    demo: bool = False                      # expliciete demo-omgeving: alles nep en zo gelabeld
    demo_home: Path = Path(".nexus-demo")
    database_url: str = "sqlite:///./nexus.db"
    admin_token: str | None = None          # nodig om de noodstop op te heffen of de modus te wijzigen
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    cache_seconds: float = 30.0
    rate_limit_per_minute: int = 30          # voor schrijvende endpoints, per IP
    anthropic_key_present: bool = False
    worker: bool = True                     # achtergrondronde voor open paper-orders en waarderingen
    worker_seconds: float = 60.0
    research_db: Path | None = None         # eigen koersopslag voor onderzoek (andere tijdschalen)
    research_out: Path | None = None        # map voor onderzoeksrapporten en het holdout-register
    jobs: bool = True                       # geplande onderzoekstaken in de worker
    council_symbols: tuple[str, ...] = ()   # dagelijkse Council-run (kost AI-budget); leeg = alleen op verzoek
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        home = os.environ.get("NEXUS_HOLDING_HOME")
        cfg = os.environ.get("NEXUS_HOLDING_CONFIG")
        origins = os.environ.get("NEXUS_CORS_ORIGINS")
        return cls(
            holding_home=Path(home).expanduser() if home else None,
            holding_config=Path(cfg).expanduser() if cfg else None,
            demo=_flag("NEXUS_DEMO"),
            demo_home=Path(os.environ.get("NEXUS_DEMO_HOME", ".nexus-demo")),
            database_url=os.environ.get("NEXUS_DATABASE_URL", "sqlite:///./nexus.db"),
            admin_token=os.environ.get("NEXUS_ADMIN_TOKEN") or None,
            cors_origins=tuple(o.strip() for o in origins.split(",")) if origins else cls.cors_origins,
            cache_seconds=float(os.environ.get("NEXUS_CACHE_SECONDS", "30")),
            anthropic_key_present=bool(os.environ.get("ANTHROPIC_API_KEY")),
            worker=os.environ.get("NEXUS_WORKER", "1") not in ("0", "false", "no"),
            worker_seconds=float(os.environ.get("NEXUS_WORKER_SECONDS", "60")),
            research_db=Path(os.environ["NEXUS_RESEARCH_DB"]).expanduser() if os.environ.get("NEXUS_RESEARCH_DB") else None,
            research_out=Path(os.environ["NEXUS_RESEARCH_OUT"]).expanduser() if os.environ.get("NEXUS_RESEARCH_OUT") else None,
            jobs=os.environ.get("NEXUS_JOBS", "1") not in ("0", "false", "no"),
            council_symbols=tuple(x.strip() for x in os.environ.get("NEXUS_COUNCIL_SYMBOLS", "").split(",") if x.strip()),
        )
