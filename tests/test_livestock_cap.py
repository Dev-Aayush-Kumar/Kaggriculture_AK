"""The livestock absorption cap must not change B0, and must bind on a glut.

The cap is a Config flag. With it off, the executor still asks for the configured
herd. With it on and milk/wool already on the $1 floor, it must not queue more
cows or sheep; freed purse still goes to seed through the existing buyer.
"""

import contextlib
import io
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make

from kagg.agent import Executor, remaining_yield_events  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.market import PRICE_FLOOR, price  # noqa: E402
from kagg.econ.tables import MARKET_I0  # noqa: E402

IDLE = {"farmer": ["PASS"], "hands": [], "market": []}

B0 = dict(routing="zone_nearest", geese=0, cows=3, sheep=3, crops=("WHEAT",),
          hands_per_day=6)
B2 = dict(B0, livestock_cap_enabled=True)


def test_remaining_yield_events_match_the_engine_refresh_rule():
    # Goose first_yield_day 4: first production is the end of day 3.
    assert remaining_yield_events("GOOSE", 0, 0, 2) == 0
    assert remaining_yield_events("GOOSE", 0, 0, 3) == 1
    # Cow first_yield_day 8, interval 2: events at end of days 7, 9, ...
    assert remaining_yield_events("COW", 0, 0, 6) == 0
    assert remaining_yield_events("COW", 0, 0, 7) == 1
    assert remaining_yield_events("COW", 0, 0, 9) == 2
    assert remaining_yield_events("SHEEP", 0, 0, 5) == 1


def test_default_config_leaves_the_cap_off():
    assert Config().livestock_cap_enabled is False
    assert Config(**B0).livestock_cap_enabled is False


def _orders_on_day0(params, market_inventory=None):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    if market_inventory:
        inv = env.state[0].observation.market["inventory"]
        inv.update(market_inventory)
    exe = Executor(Config(**params))
    obs = env.state[0].observation
    action = exe(obs, env.configuration)
    return action["market"]


def test_b0_still_buys_cows_and_sheep_on_an_empty_market():
    kinds = [o[0] + (":" + o[1] if len(o) > 1 else "") for o in _orders_on_day0(B0)]
    assert any(k == "BUY_ANIMAL:COW" for k in kinds), kinds
    assert any(k == "BUY_ANIMAL:SHEEP" for k in kinds), kinds


def test_cap_refuses_cows_and_sheep_when_milk_and_wool_are_on_the_floor():
    glut = MARKET_I0
    while price("MILK", glut) > PRICE_FLOOR or price("WOOL", glut) > PRICE_FLOOR:
        glut += 50
        assert glut < MARKET_I0 + 5000
    orders = _orders_on_day0(B2, {"MILK": glut, "WOOL": glut})
    animals = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert animals == [], animals
    # Purse that did not buy livestock must still be allowed to buy seed.
    assert any(o[0] == "BUY_SEED" for o in orders), orders


def test_cap_off_ignores_a_glutted_market():
    glut = MARKET_I0 + 4000
    orders = _orders_on_day0(B0, {"MILK": glut, "WOOL": glut})
    animals = [o[1] for o in orders if o[0] == "BUY_ANIMAL"]
    assert "COW" in animals and "SHEEP" in animals, orders


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
