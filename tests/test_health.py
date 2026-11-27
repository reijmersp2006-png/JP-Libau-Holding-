"""Master Prompt 9.3: Telegram-diagnose, toegang privé-repo, noodstop-werkflow en gezondheidsmonitor."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from jplh import health as H
from jplh.config import load_config
from jplh.paper import build_demo
from jplh.statecheck import fingerprint

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, 15, tzinfo=UTC)
GOOD = "1234567890:" + "A" * 35          # vorm van een bottoken, geen echte
needs_git = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None, reason="git/bash nodig")


def fake(responses):
    def get(url, headers=None):
        for key, val in responses.items():
            if url.endswith(key) or key in url:
                return val
        return 0, {}
    return get


# ---------------------------------------------------------------- Telegram

def test_telegram_404_is_a_malformed_token_and_never_shows_it():
    bad = " " + GOOD + "\n"                                  # zo komt een verkeerd geplakt geheim binnen
    c = H.check_telegram(bad, get=fake({"getMe": (404, {"ok": False, "description": "Not Found"})}))
    assert c.status == H.OFFLINE and "404" in c.detail and "spatie_of_regeleinde" in c.detail
    assert GOOD not in c.detail and "A" * 35 not in str(c.facts)
    c2 = H.check_telegram("bot" + GOOD, get=fake({"getMe": (404, {"description": "Not Found"})}))
    assert "begint_met_bot" in c2.detail and "vorm" in c2.detail


def test_telegram_revoked_webhook_and_healthy():
    assert "ingetrokken" in H.check_telegram(GOOD, get=fake({"getMe": (401, {"description": "Unauthorized"})})).detail
    hooked = fake({"getMe": (200, {"ok": True, "result": {}}),
                   "getWebhookInfo": (200, {"result": {"url": "https://ergens", "pending_update_count": 3}})})
    c = H.check_telegram(GOOD, get=hooked)
    assert c.status == H.DEGRADED and "webhook" in c.detail and "ergens" not in str(c.facts)
    ok = fake({"getMe": (200, {"ok": True}), "getWebhookInfo": (200, {"result": {"url": ""}})})
    assert H.check_telegram(GOOD, get=ok).status == H.HEALTHY
    assert H.check_telegram(None).status == H.OFFLINE


# ---------------------------------------------------------------- privé-repo

@pytest.mark.parametrize("args,cause", [
    ((401, 404, None, None, None, None), "TOKEN_ONGELDIG"),
    ((200, 404, None, None, None, None, ["o/jplh-state-"]), "VERKEERDE_NAAM"),
    ((200, 404, None, None, None, None, []), "NIET_GEKOPPELD"),
    ((200, 200, False, None, None, None), "NIET_PRIVE"),
    ((200, 200, True, False, None, None), "RECHTEN"),
    ((200, 200, True, True, 0, False), "RECHTEN"),
    ((200, 200, True, True, 0, True), "LEEG_OK"),
    ((200, 200, True, True, 1, True), "OK"),
    ((0, 0, None, None, None, None), "NETWERK"),
])
def test_every_access_state_has_its_own_cause(args, cause):
    assert H.classify_repo_access(*args)[0] == cause


@needs_git
def test_an_empty_private_repo_is_reported_as_reachable_not_as_an_error(tmp_path):
    bare = tmp_path / "leeg.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    def local_git(args, cwd=None):          # de https-url wordt de lokale lege repo
        args = [str(bare) if a.startswith("https://") else a for a in args]
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    get = fake({"/user": (200, {}), "/repos/o/jplh-state-": (200, {"private": True})})
    r = H.check_repo_access("o/jplh-state-", "github_pat_" + "x" * 70, get=get, git=local_git)
    assert r["oorzaak"] == "LEEG_OK" and r["branches"] == 0 and r["lezen"] and r["schrijven"]
    assert subprocess.run(["git", "--git-dir", str(bare), "branch"], capture_output=True, text=True).stdout == ""
    assert "x" * 70 not in json.dumps(r)


def test_wrong_name_lists_similar_reachable_repos_only():
    get = fake({"/user/repos": (200, [{"full_name": "o/jplh-state-"}, {"full_name": "o/iets-anders"}]),
                "/user": (200, {}), "/repos/o/jplh-state": (404, {})})
    r = H.check_repo_access("o/jplh-state", "github_pat_y", get=get, git=lambda *a, **k: (1, ""))
    assert r["oorzaak"] == "VERKEERDE_NAAM" and "o/jplh-state-" in r["uitleg"] and "iets-anders" not in r["uitleg"]


# ---------------------------------------------------------------- gezondheid

def test_scheduler_thresholds_and_overall_ignores_undeployed_gateway(tmp_path):
    ts = NOW.timestamp()
    assert H.check_scheduler(ts - 30 * 60, NOW).status == H.HEALTHY
    assert H.check_scheduler(ts - 120 * 60, NOW).status == H.DEGRADED
    assert H.check_scheduler(ts - 5 * 3600, NOW).status == H.CRITICAL
    comps = [H.Component("a", H.HEALTHY, ""), H.check_ai_gateway()]
    assert H.overall(comps) == H.HEALTHY and "telt niet mee" in H.report(comps, NOW)
    assert H.overall(comps + [H.Component("b", H.CRITICAL, "")]) == H.CRITICAL


def test_emergency_channels_and_state_storage():
    up, down = H.Component("t", H.HEALTHY, ""), H.Component("t", H.OFFLINE, "")
    assert H.emergency_channels(up, True).status == H.HEALTHY
    assert H.emergency_channels(down, True).status == H.DEGRADED
    assert H.emergency_channels(down, False).status == H.CRITICAL
    assert H.check_state_storage(None, None).status == H.DEGRADED
    assert H.check_state_storage("o/r", {"oorzaak": "NIET_GEKOPPELD"}).status == H.CRITICAL
    assert H.check_state_storage("o/r", {"oorzaak": "OK", "branches": 1}).status == H.HEALTHY


def test_database_check_flags_corruption(tmp_path):
    home = tmp_path / "h"
    build_demo(load_config(None), home, hours=6, now=NOW, history_days=3)
    assert H.check_database(home).status == H.HEALTHY
    db = home / "data" / "holding.sqlite3"
    raw = bytearray(db.read_bytes())
    raw[100:4096] = b"\xff" * (4096 - 100)
    db.write_bytes(bytes(raw))
    assert H.check_database(home).status == H.CRITICAL
    assert H.check_database(tmp_path / "leeg").status == H.CRITICAL


# ---------------------------------------------------------------- noodstop-werkflow

NOOD = yaml.safe_load((ROOT / ".github" / "workflows" / "noodstop.yml").read_text())
NSTEPS = {s["name"]: s["run"] for s in NOOD["jobs"]["noodstop"]["steps"]}


@pytest.fixture()
def state_repo(tmp_path):
    home = tmp_path / "home"
    build_demo(load_config(None), home, hours=6, now=NOW, history_days=3)
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "paper-data"], cwd=work, check=True)
    shutil.copytree(home / "data", work / "data")
    for f in work.rglob("demo"):
        if f.is_dir():
            shutil.rmtree(f)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "Paper-ronde"], cwd=work,
                   check=True)
    bare = tmp_path / "state.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return tmp_path, bare


def nood(step, cwd, bare, **env):
    script = NSTEPS[step].replace("https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git", str(bare))
    script = script.replace("sleep 5", "true")
    full = {**os.environ, "STATE_REPO": "", "GITHUB_RUN_ID": "1", "DOOR": "eigenaar", "REDEN": "test",
            "BEVESTIGING": "", **env}
    return subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=full, capture_output=True, text=True)


def run_all(cwd, bare, actie, **env):
    cwd.mkdir()
    out = ""
    for step in NSTEPS:
        if actie == "status" and step == "Noodstop zetten of opheffen":
            continue
        r = nood(step, cwd, bare, ACTIE=actie, **env)
        out += r.stdout + r.stderr
        if r.returncode:
            return r.returncode, out
    return 0, out


def show(bare, path):
    r = subprocess.run(["git", "--git-dir", str(bare), "show", f"paper-data:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


@needs_git
def test_emergency_stop_sets_kill_logs_it_and_never_touches_positions(state_repo):
    tmp, bare = state_repo
    before = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "paper-data:data"], capture_output=True,
                            text=True).stdout
    rc, out = run_all(tmp / "a", bare, "stop", REDEN="Telegram offline")
    assert rc == 0, out
    assert "AAN" in out and show(bare, "KILL").startswith("noodstop via GitHub")
    log = [json.loads(x) for x in show(bare, "noodstop-log.jsonl").splitlines()]
    assert log[-1]["actie"] == "stop" and log[-1]["nu_aan"] and log[-1]["reden"] == "Telegram offline"
    after = subprocess.run(["git", "--git-dir", str(bare), "rev-parse", "paper-data:data"], capture_output=True,
                           text=True).stdout
    assert before == after                                      # posities, geschiedenis en pauzes onaangeroerd


@needs_git
def test_resume_needs_explicit_confirmation(state_repo):
    tmp, bare = state_repo
    assert run_all(tmp / "a", bare, "stop")[0] == 0
    rc, out = run_all(tmp / "b", bare, "hervat")
    assert rc != 0 and "HERVAT" in out and show(bare, "KILL") is not None
    rc, out = run_all(tmp / "c", bare, "hervat", BEVESTIGING="HERVAT")
    assert rc == 0, out
    assert show(bare, "KILL") is None
    assert len(show(bare, "noodstop-log.jsonl").splitlines()) == 2
    rc, out = run_all(tmp / "d", bare, "status")
    assert rc == 0 and "uit" in out


def test_emergency_workflow_is_owner_only_manual_and_never_concurrent_with_a_round():
    assert set(NOOD.get(True, NOOD.get("on"))) == {"workflow_dispatch"}        # yaml leest 'on' als True
    assert NOOD["concurrency"]["group"] == "noodstop"     # niet "paper": daar kan een ronde hem annuleren
    assert "github.repository_owner" in NOOD["jobs"]["noodstop"]["if"]
    text = (ROOT / ".github" / "workflows" / "noodstop.yml").read_text()
    assert "${{" not in "".join(NSTEPS.values())                     # invoer alleen via env, nooit in de shell
    assert "paused" not in text and "resume" not in text             # raakt pauzes van afdelingen niet


def test_fingerprint_includes_the_emergency_log(tmp_path):
    home = tmp_path / "h"
    build_demo(load_config(None), home, hours=6, now=NOW, history_days=3)
    a = fingerprint(home, summary=False)
    (home / "noodstop-log.jsonl").write_text("{}\n")
    assert fingerprint(home, summary=False)["digest"] != a["digest"]


PAPER = yaml.safe_load((ROOT / ".github" / "workflows" / "paper.yml").read_text())
PSTEPS = {s.get("name"): s.get("run") for s in PAPER["jobs"]["ronde"]["steps"]}


def _round_clone(tmp, bare, name):
    """Een ronde die de stand ophaalde vóórdat de noodstop gezet werd."""
    work = tmp / name
    work.mkdir()
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "paper-data", str(bare), "state"], cwd=work,
                   check=True)
    shutil.copytree(work / "state" / "data", work / "data")
    (work / "logs").mkdir()
    return work


def _paper(step, cwd):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["bash", "-e", "-c", PSTEPS[step]], cwd=cwd, env=env, capture_output=True, text=True)


@needs_git
@pytest.mark.parametrize("reread", [True, False])
def test_a_round_running_during_the_stop_can_never_undo_it(state_repo, reread):
    tmp, bare = state_repo
    rnd = _round_clone(tmp, bare, "ronde")
    assert not (rnd / "KILL").exists()
    assert run_all(tmp / "stop", bare, "stop")[0] == 0              # noodstop terwijl de ronde loopt
    if reread:                                                      # ronde komt nu pas bij het handelen
        r = _paper("Noodstop vlak voor het handelen opnieuw lezen", rnd)
        assert r.returncode == 0, r.stderr
        assert (rnd / "KILL").exists() and "geen orders" in r.stdout
    (rnd / "logs" / "ronde.jsonl").write_text("{}\n")             # wat de ronde verder bewaart
    r = _paper("Stand bewaren", rnd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert show(bare, "KILL") is not None                           # noodstop staat er nog
    assert show(bare, "logs/ronde.jsonl") == "{}\n"                # en de ronde is ook bewaard
    assert len(show(bare, "noodstop-log.jsonl").splitlines()) == 1


def test_telegram_network_errors_are_retried_and_explained_without_the_token(monkeypatch):
    import io
    import socket
    import urllib.error

    from jplh.notify import Telegram

    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky(req, timeout=None, context=None):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError(socket.timeout("timed out"))
        return Resp(b'{"ok": true, "result": []}')

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert Telegram(GOOD).call("getUpdates")["ok"] and len(calls) == 3
    calls.clear()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))))
    with pytest.raises(RuntimeError) as err:
        Telegram(GOOD).call("getUpdates")
    msg = str(err.value)
    assert "URLError" in msg and "Connection reset" in msg and GOOD not in msg


def test_git_not_found_is_split_into_missing_contents_or_username():
    git_fail = lambda args, cwd=None: (128, "remote: Repository not found.")  # noqa: E731
    base = {"/user": (200, {"login": "eigenaar"}), "/repos/o/jplh-state-": (200, {"private": True})}
    r = H.check_repo_access("o/jplh-state-", "github_pat_z",
                            get=fake({"/contents/": (403, {"message": "Resource not accessible by personal access token"}),
                                      **base}), git=git_fail)
    assert r["oorzaak"] == "RECHTEN" and r["contents_api"] == "geweigerd" and "Contents" in r["uitleg"]

    def git_user(args, cwd=None):
        return (0, "") if any(a.startswith("https://eigenaar:") for a in args) else (128, "not found")
    r = H.check_repo_access("o/jplh-state-", "github_pat_z",
                            get=fake({"/contents/": (404, {"message": "This repository is empty."}), **base}),
                            git=git_user)
    assert r["oorzaak"] == "GIT_GEBRUIKERSNAAM" and r["git_met_eigen_naam"] is True
    assert "github_pat_z" not in json.dumps(r)


@needs_git
def test_a_stop_set_while_the_round_is_trading_reaches_it_within_seconds(state_repo):
    tmp, bare = state_repo
    rnd = _round_clone(tmp, bare, "ronde")
    assert run_all(tmp / "stopnu", bare, "stop")[0] == 0           # noodstop terwijl de ronde al handelt
    # "jplh run" wordt een ronde die per 'order' naar KILL kijkt, zoals de risicocheck doet
    fake_run = "for i in $(seq 1 40); do [ -f KILL ] && exit 0; sleep 0.25; done; exit 9"
    script = PSTEPS["Paper-ronde"].replace("sleep 5", "sleep 1").replace("jplh run", f"( {fake_run} )")
    r = subprocess.run(["bash", "-e", "-c", script], cwd=rnd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr                   # de 'ronde' zag KILL binnen 10 s
    assert (rnd / "KILL").read_text().startswith("noodstop via GitHub") and "stond aan" in r.stdout


def test_round_watcher_never_hides_a_failed_round():
    text = PSTEPS["Paper-ronde"]
    assert "jplh run || rc=$?" in text and 'exit "$rc"' in text and 'kill "$wachter"' in text
