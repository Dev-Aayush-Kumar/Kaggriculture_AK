"""Idle shed walks stay on the original count rule unless the EV flag is on."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import shed_trip_justified  # noqa: E402
from kagg.config import Config  # noqa: E402


def test_default_config_leaves_move_ev_off():
    assert Config().move_ev_enabled is False
    assert Config(livestock_cap_enabled=True).move_ev_enabled is False


def test_flag_off_uses_the_count_threshold():
    assert shed_trip_justified(3, 1000, 6, hour=10, turns_per_day=24,
                               drop_threshold=4, move_ev_enabled=False,
                               min_trip_value_per_step=10) is False
    assert shed_trip_justified(4, 0, 6, hour=10, turns_per_day=24,
                               drop_threshold=4, move_ev_enabled=False,
                               min_trip_value_per_step=10) is True


def test_flag_on_requires_quote_value_to_cover_the_walk():
    # 4 units at $1, six tiles: $4 < 10*6, so stay put.
    assert shed_trip_justified(4, 4, 6, hour=10, turns_per_day=24,
                               drop_threshold=4, move_ev_enabled=True,
                               min_trip_value_per_step=10) is False
    # One milk-priced load covers the same walk.
    assert shed_trip_justified(1, 160, 6, hour=10, turns_per_day=24,
                               drop_threshold=4, move_ev_enabled=True,
                               min_trip_value_per_step=10) is True


def test_late_day_walks_even_when_the_load_is_cheap():
    assert shed_trip_justified(1, 1, 8, hour=20, turns_per_day=24,
                               drop_threshold=4, move_ev_enabled=True,
                               min_trip_value_per_step=10) is True


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
