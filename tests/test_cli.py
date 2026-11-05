from jplh.cli import main


def test_selftest_and_status(tmp_path, capsys):
    assert main(["--home", str(tmp_path), "selftest"]) == 0
    out = capsys.readouterr().out
    assert out.count("OK") >= 6
    assert main(["--home", str(tmp_path), "collect", "--demo", "--limit", "10"]) == 0
    assert main(["--home", str(tmp_path), "status"]) == 0
    assert "180 candles" in capsys.readouterr().out


def test_kill_unkill(tmp_path):
    main(["--home", str(tmp_path), "kill"])
    assert (tmp_path / "KILL").exists()
    main(["--home", str(tmp_path), "unkill"])
    assert not (tmp_path / "KILL").exists()
