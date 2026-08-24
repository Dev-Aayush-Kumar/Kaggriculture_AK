"""plant_latest_hour stays off on P1-S/H4; a cutoff only blocks late PLANT."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.agent import plant_hour_allowed  # noqa: E402
from kagg.config import Config  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)
D1 = dict(H4, plant_latest_hour=22)


def test_plant_cutoff_defaults_off():
    assert Config().plant_latest_hour == -1
    assert Config(**B.P1_S).plant_latest_hour == -1
    assert Config(**H4).plant_latest_hour == -1
    assert Config(**H4).endgame_rescue_feed is True
    assert Config(**H4).hands_per_day == 6
    assert Config(**H4).extra_crop == ""


def test_flag_off_allows_every_hour():
    for hour in range(24):
        assert plant_hour_allowed(hour, -1) is True
        assert plant_hour_allowed(hour, Config().plant_latest_hour) is True
        assert plant_hour_allowed(hour, Config(**H4).plant_latest_hour) is True


def test_cutoff_22_blocks_only_the_last_hour():
    for hour in range(23):
        assert plant_hour_allowed(hour, 22) is True, hour
    assert plant_hour_allowed(23, 22) is False
    assert plant_hour_allowed(23, Config(**D1).plant_latest_hour) is False


def test_d1_does_not_touch_h4_livestock_or_crew():
    d1 = Config(**D1)
    h4 = Config(**H4)
    assert d1.hands_per_day == h4.hands_per_day == 6
    assert d1.cows == h4.cows == 3
    assert d1.sheep == h4.sheep == 3
    assert d1.buy_land == 0
    assert d1.extra_crop == ""
    assert d1.fertilize_crops is False


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
