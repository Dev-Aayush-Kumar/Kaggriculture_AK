"""P1-S and H4 keep livestock_reserve=300; a lower reserve is experimental only."""

import contextlib
import io
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "research"))
sys.path.insert(0, os.path.join(_ROOT, "src"))

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make

import baselines as B  # noqa: E402
from kagg.agent import Executor, remaining_yield_events  # noqa: E402
from kagg.config import Config  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)


def _day0_animal_buys(params):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    obs = env.state[0].observation
    orders = Executor(Config(**params))(obs, env.configuration)["market"]
    cows = sum(o[2] for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW")
    sheep = sum(o[2] for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "SHEEP")
    return cows, sheep, orders


def test_defaults_leave_reserve_and_fertilize_untouched():
    assert Config().livestock_reserve == 300
    assert Config().fertilize_crops is False
    assert Config().feed_pickup_cap == 0
    p1s, h4 = Config(**B.P1_S), Config(**H4)
    assert p1s.livestock_reserve == 300
    assert h4.livestock_reserve == 300
    assert p1s.fertilize_crops is False
    assert h4.fertilize_crops is False
    assert p1s.feed_pickup_cap == 0
    assert h4.feed_pickup_cap == 0


def test_h4_day0_buys_two_sheep_at_reserve_300():
    cows, sheep, orders = _day0_animal_buys(H4)
    assert cows == 3 and sheep == 2, orders


def test_h4_day0_buys_three_sheep_at_reserve_280():
    cows, sheep, orders = _day0_animal_buys(dict(H4, livestock_reserve=280))
    assert cows == 3 and sheep == 3, orders


def test_late_sheep_misses_two_yield_events():
    assert remaining_yield_events("SHEEP", 0, 0, 29) == 9
    assert remaining_yield_events("SHEEP", 5, 5, 29) == 7


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
