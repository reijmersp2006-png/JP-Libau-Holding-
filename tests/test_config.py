import pytest

from jplh.config import ConfigError, load_config


def test_default_config_covers_all_desks(config):
    classes = {i.asset_class.value for i in config.instruments}
    assert classes == {"crypto", "meme", "stocks", "metals", "fx"}
    assert config.mode == "paper"
    assert config.risk.max_class_pct["meme"] <= 0.05


def test_user_may_tighten_risk(tmp_path):
    p = tmp_path / "holding.toml"
    p.write_text("[risk]\nmax_drawdown_pct = 0.10\n[risk.max_class_pct]\nmeme = 0.02\n")
    cfg = load_config(p)
    assert cfg.risk.max_drawdown_pct == 0.10
    assert cfg.risk.max_class_pct["meme"] == 0.02
    assert cfg.risk.max_class_pct["crypto"] == 0.40


@pytest.mark.parametrize("line", [
    "[risk]\nmax_drawdown_pct = 0.30",
    "[risk]\nmax_position_pct = 0.9",
    "[risk]\nmin_order_eur = 1.0",
    "[risk.max_class_pct]\nmeme = 0.5",
])
def test_user_may_not_loosen_risk(tmp_path, line):
    p = tmp_path / "holding.toml"
    p.write_text(line + "\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_live_mode_refused(tmp_path):
    p = tmp_path / "holding.toml"
    p.write_text('[holding]\nmode = "live"\n')
    with pytest.raises(ConfigError):
        load_config(p)
