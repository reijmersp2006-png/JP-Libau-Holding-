"""Master Prompt 9.1: wat mag er publiek, en wat nooit.

Twee poortwachters, allebei alleen-lezen:

* ``check_site``: het dashboard dat naar GitHub Pages gaat. Alleen bestanden van de expliciete
  allowlist, geen databases of logboeken, geen verboden sleutels in de JSON en geen bekende
  geheimen of lokale paden. Faalt de controle, dan wordt het dashboard niet gepubliceerd; de
  handelsronde en het bewaren van de stand zijn dan al klaar en merken er niets van.
* ``scan_paths``: patronen van echte geheimen (tokens, sleutels) in bestanden, voor CI.

Rapporten tonen nooit de waarde van een geheim: alleen soort, bestand en een gemaskeerde vorm.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# Het publieke dashboard bestaat uit precies deze bestanden. Iets nieuws publiceren = hier toevoegen,
# bewust en met een review.
SITE_ALLOWLIST = frozenset({
    "index.html", "stad.html", "factsheet.html", "jarvis.html",
    "state.json", "snapshot.json", "overmind.json",
})

# Sleutels die in publieke JSON nooit mogen voorkomen (op elk niveau).
FORBIDDEN_KEYS = frozenset({
    "chat", "chat_id", "token", "telegram_token", "api_key", "apikey", "secret", "password",
    "offset", "private_key", "access_token", "refresh_token", "authorization", "cookie",
})

PATTERNS: dict[str, re.Pattern[str]] = {
    "telegram-bottoken": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "github-token": re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "ai-api-key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}\b"),
    "aws-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private-key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "token-in-url": re.compile(r"https://[^/\s:@]+:(?![$]{)[^@\s/]{12,}@"),
}
# Alleen in publieke exports: lokale paden verraden de machine en de mapstructuur.
PATH_PATTERN = re.compile(r"(?:/home/[a-z_][\w-]*/|/Users/[\w.-]+/|/root/|[A-Z]:\\\\Users\\\\|/tmp/)")
BINARY_SUFFIXES = (".sqlite3", ".sqlite", ".db", ".jsonl", ".log", ".env", ".pem", ".key")


@dataclass(frozen=True)
class Finding:
    kind: str
    file: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.file} ({self.detail})"


def mask(value: str) -> str:
    """Nooit de waarde zelf: alleen lengte en de eerste twee tekens."""
    value = str(value)
    return f"{value[:2]}… ({len(value)} tekens)" if len(value) > 4 else "…"


def _keys(obj, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if str(k).lower() in FORBIDDEN_KEYS:
                out.append(here)
            out += _keys(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _keys(v, f"{path}[{i}]")
    return out


def known_secrets(home: Path | None = None, env: dict | None = None) -> list[str]:
    """Waarden die we kennen en die nooit publiek mogen: tokens uit de omgeving en de chat-id."""
    env = os.environ if env is None else env
    out = [env[k] for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "CLOUDFLARE_API_TOKEN",
                            "STATE_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY") if env.get(k)]
    if home is not None:
        db = home / "data" / "holding.sqlite3"
        if db.exists():
            from jplh.store import Store
            st = Store(db)
            try:
                chat = st.get_state("telegram", {}).get("chat")
            finally:
                st.close()
            if chat:
                out.append(str(chat))
    return [s for s in out if len(str(s)) >= 6]


PLACEHOLDERS = ("test", "example", "dummy", "fake", "xxxx", "voorbeeld")


def scan_text(text: str, name: str, secrets: list[str] = (), paths: bool = False) -> list[Finding]:
    found = [Finding(kind, name, mask(m.group(0))) for kind, pat in PATTERNS.items() for m in pat.finditer(text)
             if not any(w in m.group(0).lower() for w in PLACEHOLDERS)]
    found += [Finding("bekend-geheim", name, mask(s)) for s in secrets if s and str(s) in text]
    if paths:
        found += [Finding("lokaal-pad", name, m.group(0)) for m in PATH_PATTERN.finditer(text)]
    return found


def check_site(site: Path, secrets: list[str] = ()) -> list[Finding]:
    """Alles wat publiek gaat, tegen de allowlist en de geheimen houden."""
    found: list[Finding] = []
    if not site.is_dir():
        return [Finding("ontbreekt", str(site.name), "geen sitemap")]
    for f in sorted(p for p in site.rglob("*") if p.is_file()):
        rel = f.relative_to(site).as_posix()
        if rel not in SITE_ALLOWLIST:
            found.append(Finding("niet-toegestaan-bestand", rel, "staat niet op de allowlist"))
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".json"):
            try:
                found += [Finding("verboden-sleutel", rel, k) for k in _keys(json.loads(text))[:20]]
            except json.JSONDecodeError:
                found.append(Finding("kapotte-json", rel, "niet te lezen"))
        found += scan_text(text, rel, secrets, paths=rel.endswith(".json"))
    return found


def scan_paths(paths: list[Path], secrets: list[str] = ()) -> list[Finding]:
    """Patronen van echte geheimen in (tekst)bestanden; databases en logboeken horen niet in de repo."""
    found: list[Finding] = []
    for f in paths:
        if not f.is_file():
            continue
        if f.suffix in BINARY_SUFFIXES or (f.name.startswith(".env") and not f.name.endswith(".example")):
            found.append(Finding("operationeel-bestand", f.as_posix(), "hoort niet in de code-repo"))
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found += scan_text(text, f.as_posix(), secrets)
    return found
