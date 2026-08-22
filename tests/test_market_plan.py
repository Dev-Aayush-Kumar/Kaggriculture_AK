"""The market plan must never commit more money than the farm has.

The screening run turned up a config that bought land, then livestock, then
seed on day 0, each order individually passing its own reserve check and the
three together costing more than the farm owned. The engine does not punish
that with an error -- it fills orders by index until `_commit_unit` fails and
silently drops the rest -- so the symptom was a farm with no cash, unfed
animals, and no way back. This test makes the overcommit itself the failure.

Sale revenue is not credited: sells are queued ahead of buys and do fund them,
but the price they clear at depends on what the opponent dumps in the same
lockstep, so the executor budgets only cash in hand.
"""

import contextlib
import io
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make

from kagg.agent import MAX_MARKET_ORDERS, Executor  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.market import buy_cost  # noqa: E402
from kagg.econ.tables import (ANIMALS, CROPS, LAND_PRICES,  # noqa: E402
                              cumulative_hire_cost)

IDLE = {"farmer": ["PASS"], "hands": [], "market": []}

# The config that collapsed to $398 in the screen: it wants a $1000 quadrant,
# eight $300 geese and ten hands out of $3000 on the first morning.
GREEDY = dict(routing="zone_nearest", geese=8, crops=("WHEAT",),
              hands_per_day=10, buy_land=1)


def committed_cost(orders, obs):
    """What the buys in `orders` would cost, priced the way the engine prices them."""
    market = obs["market"]
    farm = obs["farms"][obs["player"]]
    hires = sum(1 for o in orders if o[0] == "HIRE")
    total = 0.0
    if hires:
        # Hire n costs mult * fib(n), and hires_today carries within the day.
        already = farm["hires_today"]
        total += (cumulative_hire_cost(already + hires)
                  - cumulative_hire_cost(already))
    for order in orders:
        op = order[0]
        if op == "BUY_LAND":
            total += LAND_PRICES[len(farm["unlocked_quadrants"]) - 1]
        elif op == "BUY_ANIMAL":
            total += ANIMALS[order[1]]["cost"] * order[2]
        elif op == "BUY_SEED":
            total += CROPS[order[1]]["seed"] * order[2]
        elif op == "BUY_PRODUCT":
            cost, _, _ = buy_cost(order[1], order[2], market["inventory"][order[1]])
            total += cost
    return total


def _drive(params, seed=0, days=8):
    """Run a real episode and yield (observation, planned orders) each turn."""
    steps = days * 24
    env = make("kaggriculture", configuration={"episodeSteps": steps, "seed": seed})
    env.reset(num_agents=2)
    exe = Executor(Config(**params))
    while not env.done:
        obs = env.state[0].observation
        action = exe(obs, env.configuration)
        yield obs, action["market"]
        env.step([action, IDLE])


def test_planned_buys_never_exceed_cash_on_hand():
    worst = (0.0, None)
    for obs, orders in _drive(GREEDY):
        money = obs["farms"][obs["player"]]["money"]
        cost = committed_cost(orders, obs)
        assert cost <= money + 1e-6, (
            f"day {obs['day']} hour {obs['hour']}: committed {cost:.0f} "
            f"against {money:.0f} on hand -- {orders}")
        if money and cost / money > worst[0]:
            worst = (cost / money, (obs["day"], obs["hour"]))
    assert worst[0] > 0.5, ("the greedy config should spend most of its cash at "
                            f"some point, peaked at {worst[0]:.0%}")


def test_order_cap_is_respected_and_orders_are_well_formed():
    for obs, orders in _drive(GREEDY):
        assert len(orders) <= MAX_MARKET_ORDERS, orders
        for order in orders:
            assert isinstance(order, list) and order, order
            if order[0] in ("BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "SELL"):
                assert len(order) == 3 and isinstance(order[2], int), order
                assert order[2] > 0, order


def test_land_is_never_queued_ahead_of_livestock_or_seed():
    """Land earns nothing on its own, so it must not outbid the things that do.

    Buying it first is exactly what starved the animals in the screening run.
    """
    for obs, orders in _drive(GREEDY, days=12):
        kinds = [o[0] for o in orders]
        if "BUY_LAND" not in kinds:
            continue
        after = kinds[kinds.index("BUY_LAND") + 1:]
        assert "BUY_ANIMAL" not in after and "BUY_SEED" not in after, (
            f"land queued ahead of production: {orders}")


def test_land_is_still_bought_when_the_farm_can_afford_it():
    """The demotion must not turn `buy_land` into a dead knob: a config with no
    livestock bill accumulates surplus and should take the quadrant."""
    land_free = dict(routing="zone_nearest", geese=0, crops=("WHEAT",),
                     hands_per_day=6, buy_land=1)
    for obs, orders in _drive(land_free, days=12):
        if any(o[0] == "BUY_LAND" for o in orders):
            money = obs["farms"][obs["player"]]["money"]
            assert money >= LAND_PRICES[0], money
            return
    raise AssertionError("a farm with no animals to feed never bought land")


def test_animals_are_not_bought_once_they_cannot_reach_first_yield():
    """E7: an animal placed later than first_yield_day from the end never pays."""
    for obs, orders in _drive(GREEDY, days=6):
        last_day = (6 * 24 - 2) // 24
        for order in orders:
            if order[0] == "BUY_ANIMAL":
                assert obs["day"] + ANIMALS[order[1]]["first_yield_day"] <= last_day, (
                    f"day {obs['day']}: bought {order[1]} too late to produce")


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
