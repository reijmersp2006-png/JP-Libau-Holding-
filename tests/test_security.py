"""Master Prompt 9.1: publieke export alleen via allowlist, geen geheimen, chat-id uit de stand."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jplh.cli import main
from jplh.config import load_config
from jplh.notify import notify
from jplh.paper import build_demo
from jplh.security import SITE_ALLOWLIST, check_site, known_secrets, mask, scan_paths, scan_text
from jplh.store import Store

NOW = datetime(2026, 11, 23, 15, tzinfo=UTC)
CHAT = "9876543210"
FAKE_BOT = "1234567890:" + "A" * 35          # vorm van een bottoken, geen echte


@pytest.fixture(scope="module")
def demo_site(tmp_path_factory):
    home = tmp_path_factory.mktemp("sec")
    site = build_demo(load_config(None), home / "demo", hours=6, now=NOW, history_days=10)
    return site


def test_demo_site_passes_and_ships_only_allowlisted_files(demo_site):
    assert {p.name for p in demo_site.iterdir()} <= SITE_ALLOWLIST
    assert check_site(demo_site, [CHAT]) == []


def test_unknown_file_database_or_log_is_blocked(demo_site, tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    for p in demo_site.iterdir():
        (site / p.name).write_bytes(p.read_bytes())
    (site / "holding.sqlite3").write_bytes(b"SQLite format 3\0")
    (site / "logs").mkdir()
    (site / "logs" / "journal.jsonl").write_text("{}")
    kinds = {(f.kind, f.file) for f in check_site(site)}
    assert ("niet-toegestaan-bestand", "holding.sqlite3") in kinds
    assert ("niet-toegestaan-bestand", "logs/journal.jsonl") in kinds


def test_secret_key_chat_id_and_local_path_are_blocked_without_printing_them(demo_site, tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    state = json.loads((demo_site / "state.json").read_text())
    state["telegram"] = {"chat": CHAT}
    state["note"] = f"pad /home/phil/jplh en {FAKE_BOT}"
    (site / "state.json").write_text(json.dumps(state))
    found = check_site(site, [CHAT])
    kinds = {f.kind for f in found}
    assert {"verboden-sleutel", "bekend-geheim", "lokaal-pad", "telegram-bottoken"} <= kinds
    report = "\n".join(map(str, found))
    assert CHAT not in report and FAKE_BOT not in report and "A" * 35 not in report


def test_mask_never_reveals_more_than_two_characters():
    assert mask(CHAT) == "98… (10 tekens)" and mask("abc") == "…"


def test_placeholders_are_not_secrets_but_real_shapes_are(tmp_path):
    assert scan_text('KEY = "sk-test-SECRET-value-1234567890"', "t") == []
    assert scan_text("sk-ant-" + "b" * 40, "t")[0].kind == "ai-api-key"
    env = tmp_path / ".env"
    env.write_text("X=1")
    (tmp_path / ".env.example").write_text("X=")
    assert [f.kind for f in scan_paths([env, tmp_path / ".env.example"])] == ["operationeel-bestand"]


def test_known_secrets_include_stored_chat_and_env(tmp_path):
    st = Store(tmp_path / "data" / "holding.sqlite3")
    st.set_state("telegram", {"chat": CHAT})
    st.close()
    got = known_secrets(tmp_path, env={"TELEGRAM_TOKEN": FAKE_BOT})
    assert CHAT in got and FAKE_BOT in got


def test_publish_check_cli_exit_codes(demo_site, tmp_path, capsys):
    assert main(["--home", str(tmp_path), "publish-check", "--site", str(demo_site)]) == 0
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "secrets.env").write_text("x")
    assert main(["--home", str(tmp_path), "publish-check", "--site", str(bad)]) == 1
    assert "GEBLOKKEERD" in capsys.readouterr().out


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def find_chat(self):
        return "stranger"

    def send(self, chat, text):
        self.sent.append((chat, text))


def _quiet_state():
    return {"demo": False, "desks": [], "total": {}, "jarvis": {}, "feed": []}


def test_chat_id_secret_keeps_it_out_of_the_stored_state(tmp_path, monkeypatch):
    market = Store(tmp_path / "m.sqlite3")
    market.set_state("telegram", {"chat": CHAT, "seen_ts": NOW.isoformat()})
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    tg = FakeTelegram()
    notify(_quiet_state(), market, NOW, log=lambda *_: None, client=tg)
    mem = market.get_state("telegram")
    assert "chat" not in mem and mem["connected"] is True
    assert all(c == CHAT for c, _ in tg.sent)
    assert not any("verbonden" in t for _, t in tg.sent)      # geen nieuwe welkomstgroet


def test_without_secret_after_connecting_jarvis_never_adopts_a_stranger(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    market = Store(tmp_path / "m.sqlite3")
    market.set_state("telegram", {"connected": True, "seen_ts": NOW.isoformat()})
    tg = FakeTelegram()
    assert notify(_quiet_state(), market, NOW, log=lambda *_: None, client=tg) == 0
    assert tg.sent == [] and "chat" not in market.get_state("telegram")


def test_workflows_keep_public_fallback_and_gate_pages():
    wf = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    paper = (wf / "paper.yml").read_text()
    assert "jplh publish-check" in paper
    assert paper.index("jplh publish-check") < paper.index("upload-pages-artifact")
    assert paper.index("Stand bewaren") < paper.index("jplh publish-check")   # stand eerst veilig
    for name in ("paper.yml", "jarvis.yml"):
        text = (wf / name).read_text()
        assert "vars.STATE_REPO" in text and "secrets.STATE_TOKEN" in text and "TELEGRAM_CHAT_ID" in text
        assert "Privé-opslag onbereikbaar of leeg" in text                 # nooit stil opnieuw beginnen


def test_tracked_repository_files_contain_no_secrets():
    root = Path(__file__).resolve().parents[1]
    try:
        files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("geen git-checkout")
    assert scan_paths([root / f for f in files.split()]) == []
