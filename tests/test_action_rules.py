"""Pin `check_unit_action` to the engine's actual behaviour.

The contract we rely on everywhere is:

    check_unit_action(...) == OK   <=>   the engine mutated the farm

This test enforces it by feeding actions to the engine's own
`_apply_unit_action` against a deep copy and comparing "did anything change"
with our prediction, both over hand-built edge cases and over every action a
real episode of the executor actually emits.
"""

import contextlib
import copy
import io
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "research"))

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make
    from kaggle_environments.envs.kaggriculture import kaggriculture as eng

from kagg.actions import OK, blocked_plant_crops, check_unit_action  # noqa: E402
from kagg.agent import Executor  # noqa: E402
from kagg.config import Config  # noqa: E402

BOARD = 10
CAP = 100


def _blank_farm():
    return eng._new_farm(BOARD, 3000)


def _apply(farm, private, idx, action, day=0):
    """Run the engine on copies and report whether anything actually changed."""
    f, p = copy.deepcopy(farm), copy.deepcopy(private)
    eng._apply_unit_action(f, p, idx, action, BOARD, day, 24, CAP)
    return (f, p) != (farm, private)


def _expect(farm, private, idx, action, day=0, blocked=()):
    ours = check_unit_action(action, farm, private, idx, day, BOARD, CAP, blocked) == OK
    theirs = _apply(farm, private, idx, action, day)
    assert ours == theirs, (action, f"ours={ours}", f"engine_changed={theirs}")


def test_movement_and_bounds():
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [0, 0]
    for op in ("NORTH", "WEST"):
        _expect(farm, private, 0, [op])          # off the board, no-op
    for op in ("SOUTH", "EAST"):
        _expect(farm, private, 0, [op])
    _expect(farm, private, 0, ["PASS"])
    _expect(farm, private, 0, ["NONSENSE"])
    _expect(farm, private, 0, [])


def test_locked_tiles_block_tile_ops_but_not_shed_ops():
    """Three of the four shed-access tiles start locked; the shed still works."""
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [5, 4]                      # locked NE shed-access tile
    assert farm["tiles"][4][5] == "LOCKED"
    private["seeds"]["WHEAT"] = 1
    _expect(farm, private, 0, ["PLANT", "WHEAT"])
    _expect(farm, private, 0, ["BUILD_COOP"])
    private["shed"]["WHEAT"] = 5
    _expect(farm, private, 0, ["PICKUP", "WHEAT", 2])


def test_planting_requires_empty_tile_and_seed():
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [1, 1]
    _expect(farm, private, 0, ["PLANT", "WHEAT"])          # no seed
    private["seeds"]["WHEAT"] = 1
    _expect(farm, private, 0, ["PLANT", "WHEAT"])          # ok
    _expect(farm, private, 0, ["PLANT", "NOT_A_CROP"])
    farm["tiles"][1][1] = {"kind": "WEED"}
    _expect(farm, private, 0, ["PLANT", "WHEAT"])          # occupied


def test_watering_and_harvest_windows():
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [2, 2]
    farm["tiles"][2][2] = eng._new_plant("WHEAT", 0, 24)
    _expect(farm, private, 0, ["WATER"])
    farm["tiles"][2][2]["watered_today"] = True
    _expect(farm, private, 0, ["WATER"])                   # already watered
    _expect(farm, private, 0, ["HARVEST"], day=0)          # immature
    _expect(farm, private, 0, ["HARVEST"], day=4)          # ripe
    farm["tiles"][2][2]["yield_units"] = 0
    _expect(farm, private, 0, ["HARVEST"], day=4)          # nothing on it


def test_animal_care_feed_and_fertilizer():
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [3, 3]
    farm["tiles"][3][3] = eng._new_animal("GOOSE", 0)
    inv = private["inventories"][0]
    _expect(farm, private, 0, ["FEED"])                    # no wheat carried
    inv["WHEAT"] = 1
    _expect(farm, private, 0, ["FEED"])
    _expect(farm, private, 0, ["CARE"])
    farm["tiles"][3][3]["cared_today"] = True
    _expect(farm, private, 0, ["CARE"])                    # already cared
    _expect(farm, private, 0, ["COLLECT_FERTILIZER"])      # none ready
    farm["tiles"][3][3]["fertilizer_available"] = True
    _expect(farm, private, 0, ["COLLECT_FERTILIZER"])
    _expect(farm, private, 0, ["DIG"])                     # animal cannot be dug


def test_shed_operations():
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [4, 4]
    _expect(farm, private, 0, ["DROP"])                    # carrying nothing
    private["inventories"][0]["EGG"] = 3
    _expect(farm, private, 0, ["DROP"])
    _expect(farm, private, 0, ["PICKUP", "WHEAT", 1])      # shed empty
    private["shed"]["WHEAT"] = 4
    _expect(farm, private, 0, ["PICKUP", "WHEAT", 2])
    _expect(farm, private, 0, ["PICKUP", "WHEAT", 0])      # bad quantity
    private["shed"]["WHEAT"] = CAP                         # shed full
    _expect(farm, private, 0, ["PLACE", "EGG", 1])
    farm["farmer"] = [0, 0]
    _expect(farm, private, 0, ["DROP"])                    # not shed adjacent


def test_place_animal_on_structure():
    farm, private = _blank_farm(), eng._new_private()
    farm["farmer"] = [1, 2]
    farm["tiles"][2][1] = {"kind": "COOP"}
    _expect(farm, private, 0, ["PLACE", "GOOSE"])          # not carrying one
    private["inventories"][0]["GOOSE"] = 1
    _expect(farm, private, 0, ["PLACE", "GOOSE"])
    _expect(farm, private, 0, ["PLACE", "COW"])            # wrong structure


def test_hand_indexing_and_missing_units():
    farm, private = _blank_farm(), eng._new_private()
    farm["hands"] = [[4, 4]]
    private["inventories"].append({"EGG": 1})
    _expect(farm, private, 1, ["DROP"])
    _expect(farm, private, 2, ["DROP"])                    # no such hand


def test_atomic_plant_contention_matches_engine():
    """Two PLANT requests against one seed make the engine drop both."""
    seeds = {"WHEAT": 1}
    assert blocked_plant_crops([["PLANT", "WHEAT"], ["PLANT", "WHEAT"]], seeds) == {"WHEAT"}
    assert blocked_plant_crops([["PLANT", "WHEAT"]], seeds) == set()

    env = make("kaggriculture", configuration={"episodeSteps": 72, "seed": 3})
    env.reset(num_agents=2)
    idle = {"farmer": ["PASS"], "hands": [], "market": []}
    env.step([{"farmer": ["PASS"], "hands": [],
               "market": [["HIRE"], ["BUY_SEED", "WHEAT", 1]]}, idle])
    env.step([{"farmer": ["PLANT", "WHEAT"], "hands": [["PLANT", "WHEAT"]],
               "market": []}, idle])
    obs = env.state[0].observation
    planted = sum(1 for row in obs["farms"][0]["tiles"] for t in row
                  if isinstance(t, dict) and t.get("kind") == "PLANT")
    assert planted == 0, "engine should have dropped both contended PLANTs"
    assert obs["private"]["seeds"]["WHEAT"] == 1, "seed should be unspent"


def test_executor_actions_are_all_effective_on_a_real_episode():
    """Every action the executor emits in a live game must move the engine.

    This is the strong form of the contract: it runs the real interpreter and
    checks our prediction against observed mutation, turn by turn.
    """
    env = make("kaggriculture", configuration={"episodeSteps": 24 * 6, "seed": 11})
    env.reset(num_agents=2)
    exe = Executor(Config(geese=3, crops=("WHEAT",), hands_per_day=4))
    idle = {"farmer": ["PASS"], "hands": [], "market": []}
    checked = passes = 0

    while not env.done:
        obs = env.state[0].observation
        action = exe(obs, env.configuration)
        farm, private = obs["farms"][0], obs["private"]
        units = [action["farmer"], *action["hands"]]
        blocked = blocked_plant_crops(units, private["seeds"])
        assert len(action["hands"]) == len(farm["hands"]), "one action per hand"
        assert len(action["market"]) <= 10, "market order cap"
        for idx, act in enumerate(units):
            predicted = check_unit_action(act, farm, private, idx, obs["day"],
                                          BOARD, CAP, blocked)
            changed = _apply(farm, private, idx, act, obs["day"])
            assert (predicted == OK) == changed, (obs["day"], obs["hour"], idx, act,
                                                  predicted, changed)
            checked += 1
            passes += 1 if act == ["PASS"] else 0
        env.step([action, idle])

    assert checked > 500, f"expected a meaningful sample, got {checked}"
    print(f"  validated {checked:,} live actions ({passes:,} deliberate passes)")


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
