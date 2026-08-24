"""H4 keeps hands_per_day=6; extra crew is experimental only."""

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
from kagg.agent import Executor, World  # noqa: E402
from kagg.config import Config  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)
H5 = dict(H4, hands_per_day=8)


def _day0_orders(params):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    return Executor(Config(**params))(env.state[0].observation, env.configuration)["market"]


def test_h4_hands_stay_at_six():
    assert Config().hands_per_day == 6
    assert Config(**B.P1_S).hands_per_day == 6
    assert Config(**H4).hands_per_day == 6
    assert Config(**H4).extra_crop == ""


def test_h5_day0_still_buys_three_cows_and_two_sheep():
    orders = _day0_orders(H5)
    cows = sum(o[2] for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW")
    sheep = sum(o[2] for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "SHEEP")
    hires = sum(1 for o in orders if o[0] == "HIRE")
    assert hires == 8, orders
    assert cows == 3 and sheep == 2, orders


def test_h5_does_not_open_more_wheat_tiles():
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    obs = env.state[0].observation
    w4 = World(obs, env.configuration)
    w5 = World(obs, env.configuration)
    _, c4 = Executor(Config(**H4))._layout(w4)
    _, c5 = Executor(Config(**H5))._layout(w5)
    assert len(c4) == len(c5) == 19


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
