"""Master Prompt 9.3: herstel en bewaking van de infrastructuur. Alleen lezen, nooit waarden tonen.

Vier standen per onderdeel:

- ``HEALTHY``   werkt zoals bedoeld;
- ``DEGRADED``  werkt, maar met minder reserve of een waarschuwing (geen directe actie nodig);
- ``OFFLINE``   onderdeel onbereikbaar, de handel zelf is nog veilig;
- ``CRITICAL``  de stand of de veiligheid van de handel staat op het spel: nu ingrijpen.

Alle netwerkaanroepen gaan via één ``http``-functie die in tests vervangen wordt. Tokens staan alleen
in headers of in de Telegram-url en komen nooit in een melding terecht.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

HEALTHY, DEGRADED, OFFLINE, CRITICAL = "HEALTHY", "DEGRADED", "OFFLINE", "CRITICAL"
RANK = {HEALTHY: 0, DEGRADED: 1, OFFLINE: 2, CRITICAL: 3}
TG_SHAPE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")


@dataclass
class Component:
    name: str
    status: str
    detail: str
    counts: bool = True               # telt mee voor het totaal (False: bewust nog niet uitgerold)
    facts: dict = field(default_factory=dict)


def http(url: str, headers: dict | None = None, timeout: float = 10.0) -> tuple[int, dict]:
    """GET -> (statuscode, json). Netwerkfout = code 0. Nooit de url in een fout (er kan een token in staan)."""
    from jplh.data.http import USER_AGENT, ssl_context
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:  # noqa: BLE001
            return exc.code, {}
    except Exception:  # noqa: BLE001
        return 0, {}


# ---------------------------------------------------------------- Telegram

def telegram_shape(token: str | None) -> dict:
    """Vorm van de bottoken zonder iets van de waarde te tonen."""
    t = token or ""
    return {"aanwezig": bool(t), "lengte": len(t), "spatie_of_regeleinde": bool(re.search(r"\s", t)),
            "begint_met_bot": t.lower().startswith("bot"), "dubbele_punt": ":" in t,
            "vorm_klopt": bool(TG_SHAPE.match(t.strip()))}


def check_telegram(token: str | None, get=http) -> Component:
    """getMe (geldig?) en getWebhookInfo (staat er een webhook die getUpdates blokkeert?)."""
    shape = telegram_shape(token)
    if not token:
        return Component("Telegram API", OFFLINE, "geen TELEGRAM_TOKEN", facts=shape)
    base = "https://api.telegram.org/bot" + token + "/"
    code, body = get(base + "getMe")
    desc = str(body.get("description", ""))[:120].replace(token, "***")
    if code == 0:
        return Component("Telegram API", DEGRADED, "Telegram niet bereikbaar (netwerk)", facts=shape)
    if code == 404:
        why = "token heeft niet de juiste vorm" if not shape["vorm_klopt"] else "Telegram kent deze token niet"
        hints = [k for k in ("spatie_of_regeleinde", "begint_met_bot") if shape[k]]
        return Component("Telegram API", OFFLINE, f"HTTP 404 {desc}: {why}" + (f" ({', '.join(hints)})" if hints else ""),
                         facts=shape)
    if code == 401:
        return Component("Telegram API", OFFLINE, f"HTTP 401 {desc}: token ingetrokken of vervangen", facts=shape)
    if code != 200:
        return Component("Telegram API", DEGRADED, f"getMe HTTP {code} {desc}".rstrip(), facts=shape)
    wcode, wh = get(base + "getWebhookInfo")
    info = wh.get("result") or {}
    facts = {**shape, "webhook_ingesteld": bool(info.get("url")), "wachtende_updates": info.get("pending_update_count")}
    if wcode == 200 and info.get("url"):
        return Component("Telegram API", DEGRADED, "token geldig, maar er staat een webhook: getUpdates werkt dan niet",
                         facts=facts)
    return Component("Telegram API", HEALTHY, "token geldig, geen webhook", facts=facts)


# ---------------------------------------------------------------- GitHub / privé-opslag

def github_token_shape(token: str | None) -> dict:
    t = token or ""
    kind = "fine-grained" if t.startswith("github_pat_") else "classic" if t.startswith("ghp_") else (
        "leeg" if not t else "onbekend begin")
    return {"vorm": kind, "lengte": len(t), "spatie_of_regeleinde": bool(re.search(r"\s", t))}


def classify_repo_access(user_code: int, repo_code: int, private: bool | None, read_ok: bool | None,
                         heads: int | None, write_ok: bool | None, similar: list[str] | None = None) -> tuple[str, str]:
    """Eén oorzaak per toestand. Een lege repo (0 branches) is in orde, geen fout."""
    if user_code == 0 or repo_code == 0:
        return "NETWERK", "GitHub niet bereikbaar; later opnieuw"
    if user_code == 401:
        return "TOKEN_ONGELDIG", "GitHub kent deze token niet (verlopen, ingetrokken of verkeerd geplakt)"
    if repo_code == 404:
        if similar:
            return "VERKEERDE_NAAM", "deze naam bestaat niet voor de token; wel bereikbaar: " + ", ".join(similar)
        return "NIET_GEKOPPELD", ("repo niet zichtbaar voor de token: naam onjuist, of de repo staat niet bij "
                                  "'Only select repositories' van de token")
    if repo_code == 403:
        return "RECHTEN", "token mag deze repo niet lezen (Metadata: Read ontbreekt?)"
    if repo_code != 200:
        return "ONBEKEND", f"GitHub gaf HTTP {repo_code}"
    if private is not True:
        return "NIET_PRIVE", "repo is niet privé: geweigerd"
    if read_ok is False:
        return "RECHTEN", "repo zichtbaar, maar git-lezen geweigerd (Contents: Read ontbreekt)"
    if write_ok is False:
        return "RECHTEN", "lezen werkt, schrijven niet (Contents: Read and write nodig)"
    if heads == 0:
        return "LEEG_OK", "toegang in orde; de repo is nog leeg (verwacht vóór de verhuizing)"
    return "OK", "toegang in orde (lezen en schrijven)"


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr)


def check_repo_access(repo: str, token: str | None, get=http, git=_git) -> dict:
    """Lezen én schrijven testen zonder iets te schrijven: ``git push --dry-run`` vraagt wel
    schrijfrechten aan GitHub, maar zet niets neer."""
    shape = github_token_shape(token)
    if not token:
        return {"token": shape, "oorzaak": "GEEN_TOKEN", "uitleg": "geheim STATE_TOKEN ontbreekt"}
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    ucode, ubody = get("https://api.github.com/user", h)
    rcode, rbody = get(f"https://api.github.com/repos/{repo}", h)
    private = rbody.get("private") if rcode == 200 else None
    similar = None
    if rcode == 404 and ucode == 200:
        lcode, lst = get("https://api.github.com/user/repos?per_page=100", h)
        names = [r.get("full_name", "") for r in lst] if lcode == 200 and isinstance(lst, list) else []
        stem = repo.split("/")[-1].strip("-_.").lower()
        similar = [n for n in names if stem and stem[:6] in n.lower()]
    read_ok = heads = write_ok = None
    extra: dict = {}
    if rcode == 200 and private:
        url = f"https://x-access-token:{token}@github.com/{repo}.git"
        rc, out = git(["ls-remote", "--heads", url])
        read_ok = rc == 0
        heads = len([ln for ln in out.splitlines() if "refs/heads/" in ln]) if read_ok else None
        if not read_ok:
            # 9.3: git zegt bij ontbrekende Contents-rechten "Repository not found". De API onderscheidt het
            # wel: zonder Contents-rechten 403, met rechten 200 (of 404 "This repository is empty").
            ccode, cbody = get(f"https://api.github.com/repos/{repo}/contents/", h)
            msg = str(cbody.get("message", "")) if isinstance(cbody, dict) else ""
            contents = "geweigerd" if ccode == 403 else "ok" if ccode == 200 or "empty" in msg.lower() else f"HTTP {ccode}"
            login = ubody.get("login") if isinstance(ubody, dict) else None
            alt_ok = False
            if contents == "ok" and login:            # rechten in orde: dan ligt het aan de git-gebruikersnaam?
                alt = f"https://{login}:{token}@github.com/{repo}.git"
                rc2, out2 = git(["ls-remote", "--heads", alt])
                alt_ok = rc2 == 0
            extra = {"contents_api": contents, "git_met_eigen_naam": alt_ok if contents == "ok" else None}
        if read_ok:
            with tempfile.TemporaryDirectory() as tmp:
                git(["init", "-q", tmp])
                git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "t"], Path(tmp))
                rc, _ = git(["push", "--dry-run", "-q", url, "HEAD:refs/heads/toegangstest"], Path(tmp))
                write_ok = rc == 0
    cause, text = classify_repo_access(ucode, rcode, private, read_ok, heads, write_ok, similar)
    if extra.get("contents_api") == "geweigerd":
        text = ("GitHub bevestigt: de token heeft geen Contents-rechten op deze repo (API 403). Zet bij de token "
                "Repository permissions > Contents op 'Read and write' en klik Update")
    elif extra.get("contents_api") == "ok":
        cause, text = ("GIT_GEBRUIKERSNAAM", "rechten in orde; git werkt wel met de eigen gebruikersnaam") if extra[
            "git_met_eigen_naam"] else ("GIT_ONBEKEND", "API-rechten in orde, maar git weigert; git-melding nodig")
    return {"token": shape, "token_http": ucode, "repo_http": rcode, "prive": private, "lezen": read_ok,
            "schrijven": write_ok, "branches": heads, **extra, "oorzaak": cause, "uitleg": text}


# ---------------------------------------------------------------- overige onderdelen

def check_scheduler(last_round_ts: float | None, now: datetime) -> Component:
    if not last_round_ts:
        return Component("Handelsplanner", CRITICAL, "geen paper-ronde gevonden")
    age = (now.timestamp() - last_round_ts) / 60
    if age <= 75:
        return Component("Handelsplanner", HEALTHY, f"laatste ronde {age:.0f} min geleden")
    if age <= 180:
        return Component("Handelsplanner", DEGRADED, f"laatste ronde {age:.0f} min geleden (uur gemist)")
    return Component("Handelsplanner", CRITICAL, f"laatste ronde {age / 60:.1f} uur geleden")


def check_database(home: Path) -> Component:
    from jplh.statecheck import fingerprint
    try:
        fp = fingerprint(home, summary=False)
    except Exception as exc:  # noqa: BLE001
        return Component("Database-integriteit", CRITICAL, f"controle mislukt: {type(exc).__name__}")
    if not fp["has_data"]:
        return Component("Database-integriteit", CRITICAL, "geen stand gevonden")
    bad = [k for k, v in fp["integrity"].items() if v != "ok"]
    if bad:
        return Component("Database-integriteit", CRITICAL, f"integriteit NIET ok: {', '.join(bad)}")
    return Component("Database-integriteit", HEALTHY, f"{len(fp['integrity'])} databases ok, {fp['files']} bestanden")


def check_state_storage(state_repo: str | None, access: dict | None) -> Component:
    if not state_repo:
        return Component("Privé-opslag", DEGRADED, "nog niet in gebruik: de stand staat op de publieke branch")
    cause = (access or {}).get("oorzaak")
    if cause == "OK" and (access or {}).get("branches"):
        return Component("Privé-opslag", HEALTHY, "bereikbaar, lezen en schrijven werkt")
    return Component("Privé-opslag", CRITICAL, f"ingesteld maar niet bruikbaar: {cause}")


def check_github_auth(code: int) -> Component:
    if code == 200:
        return Component("GitHub-authenticatie", HEALTHY, "werkflow-token geldig")
    if code == 0:
        return Component("GitHub-authenticatie", DEGRADED, "GitHub API niet bereikbaar")
    return Component("GitHub-authenticatie", CRITICAL, f"GitHub weigert de werkflow-token (HTTP {code})")


def check_pages(deploy_state: str | None, age_min: float | None) -> Component:
    if deploy_state is None:
        return Component("Dashboardpublicatie", OFFLINE, "geen publicatie gevonden")
    if deploy_state != "success":
        return Component("Dashboardpublicatie", DEGRADED, f"laatste publicatie: {deploy_state}")
    if age_min is not None and age_min > 180:
        return Component("Dashboardpublicatie", DEGRADED, f"laatste geslaagde publicatie {age_min / 60:.1f} uur oud")
    return Component("Dashboardpublicatie", HEALTHY, "laatste publicatie geslaagd")


def check_ai_gateway() -> Component:
    return Component("AI Gateway", OFFLINE, "nog niet uitgerold: de holding roept geen model aan (verwacht)",
                     counts=False)


def overall(components: list[Component]) -> str:
    counted = [c for c in components if c.counts]
    return max((c.status for c in counted), key=RANK.get, default=HEALTHY)


def emergency_channels(telegram: Component, workflow_present: bool) -> Component:
    """Noodstop moet via minstens één kanaal werken. Geen kanaal = CRITICAL."""
    ok = [n for n, up in (("Telegram", telegram.status == HEALTHY), ("GitHub-werkflow", workflow_present)) if up]
    if len(ok) == 2:
        return Component("Noodstopkanalen", HEALTHY, "Telegram en GitHub-werkflow")
    if ok:
        return Component("Noodstopkanalen", DEGRADED, f"alleen {ok[0]} werkt")
    return Component("Noodstopkanalen", CRITICAL, "geen enkel noodstopkanaal werkt")


def report(components: list[Component], now: datetime | None = None) -> str:
    now = now or datetime.now(tz=UTC)
    lines = [f"Gezondheid {now:%Y-%m-%d %H:%M} UTC: {overall(components)}"]
    for c in components:
        lines.append(f"  {c.status:<9} {c.name:<22} {c.detail}" + ("" if c.counts else "  [telt niet mee]"))
    return "\n".join(lines)
