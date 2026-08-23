"""Animal harvest stays on the original always-lift rule unless the defer flag is on."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import harvest_deferred  # noqa: E402
from kagg.config import Config  # noqa: E402


def test_default_config_leaves_harvest_defer_off():
    assert Config().harvest_defer_enabled is False
    assert Config(sell_defer_enabled=True, move_ev_enabled=True).harvest_defer_enabled is False


def test_flag_off_never_defers():
    assert harvest_deferred(1, 200, 2, 6, False, 0.30) is False


def test_flag_on_holds_a_partial_load_at_a_poor_quote():
    assert harvest_deferred(1, 200, 2, 6, True, 0.30) is True
    assert harvest_deferred(59, 200, 2, 6, True, 0.30) is True
    assert harvest_deferred(60, 200, 2, 6, True, 0.30) is False


def test_flag_on_still_lifts_a_full_tile():
    assert harvest_deferred(1, 200, 6, 6, True, 0.30) is False


def test_hold_full_waits_on_a_poor_full_tile_until_the_last_day():
    assert harvest_deferred(1, 200, 6, 6, True, 0.30, True, 20, 29, 0) is True
    assert harvest_deferred(80, 200, 6, 6, True, 0.30, True, 20, 29, 0) is False
    assert harvest_deferred(1, 200, 6, 6, True, 0.30, True, 29, 29, 0) is False


def test_hold_full_off_leaves_h1_rescue_unchanged():
    assert harvest_deferred(1, 200, 6, 6, True, 0.30, False, 20, 29, 0) is False


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
