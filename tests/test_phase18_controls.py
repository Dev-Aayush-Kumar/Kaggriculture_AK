"""P1-S and H4 stay isolated; experimental knobs remain default-off."""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.config import Config  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

EXPERIMENTAL_OFF = {
    "harvest_defer_enabled": False,
    "harvest_defer_hold_full": False,
    "harvest_defer_wool_only": False,
    "endgame_rescue_feed": False,
    "sale_qty_enabled": False,
    "fertilize_crops": False,
    "extra_crop": "",
    "buy_land": 0,
    "feed_pickup_cap": 0,
    "feed_count_carried": False,
    "plant_latest_hour": -1,
}


def _fields(cfg):
    return {k: getattr(cfg, k) for k in vars(Config)
            if not k.startswith("_") and not callable(getattr(Config, k))}


def test_named_h4_matches_the_frozen_stack():
    assert B.H4["harvest_defer_enabled"] is True
    assert B.H4["harvest_defer_wool_only"] is True
    assert B.H4["endgame_rescue_feed"] is True
    p1s, h4 = _fields(Config(**B.P1_S)), _fields(Config(**B.H4))
    assert {k for k in p1s if p1s[k] != h4[k]} == {
        "harvest_defer_enabled", "harvest_defer_wool_only", "endgame_rescue_feed",
    }


def test_p1s_keeps_every_experimental_flag_off():
    cfg = Config(**B.P1_S)
    for key, value in EXPERIMENTAL_OFF.items():
        assert getattr(cfg, key) == value, key
    assert cfg.cows == 3 and cfg.sheep == 3
    assert cfg.hands_per_day == 6
    assert cfg.livestock_reserve == 300
    assert cfg.feed_buffer == 2
    assert cfg.move_ev_enabled is True
    assert cfg.sell_defer_enabled is True


def test_h4_keeps_closed_branch_flags_off():
    cfg = Config(**B.H4)
    for key, value in EXPERIMENTAL_OFF.items():
        if key in ("harvest_defer_enabled", "harvest_defer_wool_only",
                   "endgame_rescue_feed"):
            continue
        assert getattr(cfg, key) == value, key
    assert cfg.hands_per_day == 6
    assert cfg.livestock_reserve == 300
    assert cfg.feed_buffer == 2
    assert cfg.harvest_defer_enabled is True
    assert cfg.harvest_defer_wool_only is True
    assert cfg.endgame_rescue_feed is True


def test_bare_config_does_not_enable_h4_flags():
    cfg = Config()
    assert cfg.harvest_defer_enabled is False
    assert cfg.harvest_defer_wool_only is False
    assert cfg.endgame_rescue_feed is False
    assert cfg.plant_latest_hour == -1
    assert cfg.extra_crop == ""


def test_main_py_matches_named_h4():
    path = os.path.join(ROOT, "main.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    kwargs = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "CONFIG":
                call = node.value
                assert isinstance(call, ast.Call)
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    assert kwargs is not None
    assert _fields(Config(**kwargs)) == _fields(Config(**B.H4))


def test_main_py_does_not_import_research():
    path = os.path.join(ROOT, "main.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("research")
                assert alias.name != "baselines"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("research")
            assert node.module != "baselines"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
