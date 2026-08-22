"""Produce sales stay on the original floor/liquidation rule unless the defer flag is on."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import sale_justified  # noqa: E402
from kagg.config import Config  # noqa: E402


def _call(**overrides):
    args = dict(quote=200, base=200, day=20, last_day=29, shed_used=10,
                shed_capacity=100, sell_floor_fraction=0.30, liquidating=False,
                sell_defer_enabled=False, sell_defer_force_days=0,
                sell_defer_shed_frac=0.80)
    args.update(overrides)
    return sale_justified(**args)


def test_default_config_leaves_sell_defer_off():
    assert Config().sell_defer_enabled is False
    assert Config(livestock_cap_enabled=True).sell_defer_enabled is False
    assert Config(move_ev_enabled=True).sell_defer_enabled is False


def test_flag_off_sells_during_liquidation_even_at_the_dollar_floor():
    assert _call(quote=1, liquidating=True, sell_defer_enabled=False) is True
    assert _call(quote=1, liquidating=False, sell_defer_enabled=False) is False


def test_flag_off_sells_when_the_quote_clears_the_existing_floor():
    assert _call(quote=60, base=200, liquidating=False) is True
    assert _call(quote=59, base=200, liquidating=False) is False


def test_flag_on_defers_a_poor_quote_while_time_and_shed_room_remain():
    # Day 27 is inside the original 2-day liquidation window (last_day=29).
    assert _call(quote=1, day=27, last_day=29, liquidating=True,
                 sell_defer_enabled=True, sell_defer_force_days=0) is False


def test_flag_on_dumps_on_the_last_day_and_when_the_shed_is_tight():
    assert _call(quote=1, day=29, last_day=29, liquidating=True,
                 sell_defer_enabled=True, sell_defer_force_days=0) is True
    assert _call(quote=1, day=27, last_day=29, shed_used=80, shed_capacity=100,
                 liquidating=True, sell_defer_enabled=True,
                 sell_defer_force_days=0, sell_defer_shed_frac=0.80) is True


def test_flag_on_still_sells_a_healthy_quote():
    assert _call(quote=160, base=200, day=27, last_day=29, liquidating=True,
                 sell_defer_enabled=True) is True


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
