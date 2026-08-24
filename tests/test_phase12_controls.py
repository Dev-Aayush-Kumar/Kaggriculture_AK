"""P1-S, H1, H3, and H4 differ only by the stacked experimental flags."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.agent import harvest_deferred, rescue_feed_action  # noqa: E402
from kagg.config import Config  # noqa: E402

H1 = dict(B.P1_S, harvest_defer_enabled=True)
H3 = dict(H1, harvest_defer_wool_only=True)
H4 = dict(H3, endgame_rescue_feed=True)


def _cfg(params):
    return Config(**params)


def _fields(cfg):
    return {k: getattr(cfg, k) for k in vars(Config)
            if not k.startswith("_") and not callable(getattr(Config, k))}


def test_p1s_keeps_all_phase11_flags_off():
    p1s = _cfg(B.P1_S)
    assert p1s.cows == 3 and p1s.sheep == 3
    assert p1s.livestock_cap_enabled is True
    assert p1s.routing == "zone_nearest"
    assert p1s.move_ev_enabled is True
    assert p1s.sell_defer_enabled is True
    assert p1s.sale_qty_enabled is False
    assert p1s.harvest_defer_enabled is False
    assert p1s.harvest_defer_hold_full is False
    assert p1s.harvest_defer_wool_only is False
    assert p1s.endgame_rescue_feed is False


def test_h1_differs_from_p1s_only_by_harvest_defer():
    p1s, h1 = _fields(_cfg(B.P1_S)), _fields(_cfg(H1))
    assert h1["harvest_defer_enabled"] is True
    assert h1["harvest_defer_hold_full"] is False
    assert h1["harvest_defer_wool_only"] is False
    assert h1["endgame_rescue_feed"] is False
    assert {k for k in p1s if p1s[k] != h1[k]} == {"harvest_defer_enabled"}


def test_h3_differs_from_h1_only_by_wool_only():
    h1, h3 = _fields(_cfg(H1)), _fields(_cfg(H3))
    assert h3["harvest_defer_enabled"] is True
    assert h3["harvest_defer_wool_only"] is True
    assert h3["endgame_rescue_feed"] is False
    assert {k for k in h1 if h1[k] != h3[k]} == {"harvest_defer_wool_only"}


def test_h4_differs_from_h3_only_by_rescue_feed():
    h3, h4 = _fields(_cfg(H3)), _fields(_cfg(H4))
    assert h4["endgame_rescue_feed"] is True
    assert h4["harvest_defer_wool_only"] is True
    assert {k for k in h3 if h3[k] != h4[k]} == {"endgame_rescue_feed"}


def test_h3_defers_wool_not_milk():
    assert harvest_deferred(1, 160, 2, 6, True, 0.30, False, 20, 29, 0,
                            "MILK", True) is False
    assert harvest_deferred(1, 200, 2, 6, True, 0.30, False, 20, 29, 0,
                            "WOOL", True) is True


def test_p1s_and_h3_do_not_fire_on_tile_rescue():
    assert rescue_feed_action(False, 28, 29, False, 1, 1, 200) is None
    assert _cfg(B.P1_S).endgame_rescue_feed is False
    assert _cfg(H3).endgame_rescue_feed is False
    assert rescue_feed_action(_cfg(H4).endgame_rescue_feed,
                              28, 29, False, 1, 1, 200) == "FEED"


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
