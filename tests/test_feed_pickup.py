"""feed_pickup_cap is off by default; cap=1 draws one wheat per FEED trip."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.agent import feed_pickup_qty, wheat_feed_short  # noqa: E402
from kagg.config import Config  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)


def test_defaults_leave_feed_pickup_uncapped():
    assert Config().feed_pickup_cap == 0
    assert Config().feed_count_carried is False
    assert Config(**B.P1_S).feed_pickup_cap == 0
    assert Config(**H4).feed_pickup_cap == 0
    assert Config(**B.P1_S).feed_count_carried is False
    assert Config(**H4).feed_count_carried is False


def test_cap_off_takes_one_wheat_per_animal():
    assert feed_pickup_qty(20, 6, 0) == 6
    assert feed_pickup_qty(3, 6, 0) == 3
    assert feed_pickup_qty(0, 6, 0) == 1


def test_cap_one_takes_a_single_wheat():
    assert feed_pickup_qty(20, 6, 1) == 1
    assert feed_pickup_qty(3, 6, 1) == 1
    assert feed_pickup_qty(0, 6, 1) == 1


def test_h4_and_p1s_keep_the_original_n_animals_draw():
    for params in (B.P1_S, H4):
        cap = Config(**params).feed_pickup_cap
        assert feed_pickup_qty(20, 6, cap) == 6


def test_carried_wheat_does_not_fill_the_buffer_by_default():
    assert wheat_feed_short(6, 12, 6, 2, False) == 6
    assert wheat_feed_short(12, 0, 6, 2, False) == 0


def test_carried_wheat_fills_the_buffer_when_counted():
    assert wheat_feed_short(6, 12, 6, 2, True) == 0
    assert wheat_feed_short(6, 4, 6, 2, True) == 2
    assert wheat_feed_short(0, 0, 6, 2, True) == 12


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
