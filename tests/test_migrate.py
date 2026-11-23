"""Master Prompt 9.2: de verhuisworkflow echt uitvoeren tegen lokale git-repo's.

De bash-stappen komen letterlijk uit .github/workflows/state-migrate.yml; alleen `gh` is een stub.
Bewijst: identieke kopie, MOVED-markering, nooit overschrijven bij afwijking, en een werkende rollback.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from jplh.config import load_config
from jplh.paper import build_demo
from jplh.statecheck import compare, fingerprint

ROOT = Path(__file__).resolve().parents[1]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "state-migrate.yml").read_text())
STEPS = {s.get("name"): s["run"] for s in WF["jobs"]["verhuizen"]["steps"] if "run" in s}
NOW = datetime(2026, 11, 23, 15, tzinfo=UTC)

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None, reason="git/bash nodig")


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def world(tmp_path):
    """Een publieke repo met branch paper-data (demo-stand) en een lege privé-repo."""
    home = tmp_path / "home"
    build_demo(load_config(None), home, hours=6, now=NOW, history_days=6)
    work = tmp_path / "work"
    work.mkdir()
    git("init", "-q", "-b", "paper-data", cwd=work)
    for d in ("data", "logs"):
        if (home / d).exists():
            shutil.copytree(home / d, work / d)
    for f in work.rglob("demo"):
        if f.is_dir():
            shutil.rmtree(f)
    (work / "jarvis.json").write_text('{"offset": 1}')
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "Paper-ronde test", cwd=work)
    pub, priv = tmp_path / "pub.git", tmp_path / "priv.git"
    git("clone", "-q", "--bare", str(work), str(pub))
    git("init", "-q", "--bare", str(priv))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text("#!/bin/sh\necho 0\n")
    (bin_ / "gh").chmod(0o755)
    (bin_ / "jplh").write_text(f"#!/bin/sh\nexec {sys.executable} -m jplh.cli \"$@\"\n")
    (bin_ / "jplh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "PUB": str(pub), "PRIV": str(priv),
           "GITHUB_REPOSITORY": "x/publiek", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return tmp_path, pub, priv, env


def run(step, cwd, env):
    script = STEPS[step].replace("sleep 30", "true").replace("sleep 10", "true")
    return subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=env, capture_output=True, text=True)


def head(repo):
    return git("--git-dir", str(repo), "rev-parse", "paper-data")


def test_check_mode_proves_identical_copy_and_leaves_no_trace(world):
    tmp, pub, priv, env = world
    before = head(pub)
    (tmp / "c").mkdir()
    r = run("Controle - tijdelijke kopie, echte stand onaangeroerd", tmp / "c", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IDENTIEK" in r.stdout and "gelukt" in r.stdout
    assert head(pub) == before
    assert git("--git-dir", str(priv), "branch", "--list") == ""          # tijdelijke branch weer weg


def test_move_copies_everything_marks_public_and_is_idempotent(world):
    tmp, pub, priv, env = world
    (tmp / "m").mkdir()
    r = run("Verhuizen", tmp / "m", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IDENTIEK" in r.stdout and head(pub) == head(priv)
    assert "MOVED" in git("--git-dir", str(pub), "ls-tree", "--name-only", "paper-data")
    # nog een keer draaien verandert niets en faalt niet
    (tmp / "m2").mkdir()
    again = run("Verhuizen", tmp / "m2", env)
    assert again.returncode == 0, again.stdout + again.stderr
    assert head(pub) == head(priv)


def test_move_refuses_when_private_has_a_different_state(world):
    tmp, pub, priv, env = world
    other = tmp / "other"
    other.mkdir()
    git("init", "-q", "-b", "paper-data", cwd=other)
    (other / "x").write_text("lege of afwijkende stand")
    git("add", "-A", cwd=other)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "anders", cwd=other)
    git("push", "-q", str(priv), "paper-data", cwd=other)
    before_pub, before_priv = head(pub), head(priv)
    (tmp / "m").mkdir()
    r = run("Verhuizen", tmp / "m", env)
    assert r.returncode != 0 and "afwijkende stand" in r.stdout
    assert head(pub) == before_pub and head(priv) == before_priv          # niets overschreven


def test_rollback_restores_public_branch_with_later_rounds(world):
    tmp, pub, priv, env = world
    (tmp / "m").mkdir()
    assert run("Verhuizen", tmp / "m", env).returncode == 0
    # een latere ronde in de privé-repo
    w = tmp / "w"
    git("clone", "-q", "--branch", "paper-data", str(priv), str(w))
    (w / "jarvis.json").write_text('{"offset": 2}')
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "Paper-ronde privé", cwd=w)
    git("push", "-q", "origin", "paper-data", cwd=w)
    (tmp / "r").mkdir()
    r = run("Terugzetten (rollback)", tmp / "r", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "IDENTIEK" in r.stdout and head(pub) == head(priv)
    names = git("--git-dir", str(pub), "ls-tree", "--name-only", "paper-data")
    assert "MOVED" not in names
    assert json.loads(git("--git-dir", str(pub), "show", "paper-data:jarvis.json"))["offset"] == 2


def test_fingerprint_is_read_only_and_detects_any_change(tmp_path):
    home = tmp_path / "h"
    build_demo(load_config(None), home, hours=6, now=NOW, history_days=6)
    a = fingerprint(home)
    assert a["integrity_ok"] and a["has_data"] and fingerprint(home)["digest"] == a["digest"]
    assert all(set(r) >= {"equity_eur", "positions", "paused"} for r in a["desks"].values())
    log = next((home / "logs").rglob("*.jsonl"))
    log.write_text(log.read_text() + "{}\n")
    assert any(d.startswith("digest") for d in compare(a, fingerprint(home)))


def test_workflows_refuse_the_old_public_copy_after_the_move():
    for name in ("paper.yml", "jarvis.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        assert '[ -z "$STATE_REPO" ] && [ -f state/MOVED ]' in text
        assert text.index("state/MOVED") < text.index("cp -r state/data/. data/")
