"""Last-day rescue feed stays off unless the E47 class-C conditions hold."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import rescue_feed_action  # noqa: E402
from kagg.config import Config  # noqa: E402


def test_default_config_leaves_rescue_off():
    assert Config().endgame_rescue_feed is False
    assert Config(harvest_defer_enabled=True,
                  harvest_defer_wool_only=True).endgame_rescue_feed is False


def test_flag_off_never_rescues():
    assert rescue_feed_action(False, 28, 29, False, 1, 2, 200) is None


def test_on_tile_with_wheat_feeds_a_valuable_escape():
    assert rescue_feed_action(True, 28, 29, False, 1, 1, 200) == "FEED"


def test_poor_remaining_value_is_not_rescued():
    assert rescue_feed_action(True, 28, 29, False, 1, 1, 24) is None
    assert rescue_feed_action(True, 28, 29, False, 1, 1, 25) is None


def test_only_the_day_before_last_qualifies():
    assert rescue_feed_action(True, 27, 29, False, 1, 1, 200) is None
    assert rescue_feed_action(True, 29, 29, False, 1, 1, 200) is None


def test_already_fed_or_not_yet_at_risk_is_left_alone():
    assert rescue_feed_action(True, 28, 29, True, 1, 1, 200) is None
    assert rescue_feed_action(True, 28, 29, False, 0, 1, 200) is None


def test_no_wheat_in_hand_does_not_start_a_chase():
    assert rescue_feed_action(True, 28, 29, False, 1, 0, 200) is None


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
