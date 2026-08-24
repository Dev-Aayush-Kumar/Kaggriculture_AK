"""extra_crop stays off on P1-S/H4; CARROT uses non-NW tiles and pinned livestock."""

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
from kagg.econ.tables import quadrant_of  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)
C1 = dict(H4, extra_crop="CARROT", buy_land=1, tiles_per_unit=4.0)


def test_extra_crop_defaults_off():
    assert Config().extra_crop == ""
    assert Config(**B.P1_S).extra_crop == ""
    assert Config(**H4).extra_crop == ""
    assert Config(**H4).buy_land == 0
    assert Config(**H4).tiles_per_unit == 3.0


def test_crop_for_tile_keeps_wheat_on_nw():
    exe = Executor(Config(**C1))
    assert exe._crop_for_tile((0, 0), 10) == "WHEAT"
    assert exe._crop_for_tile((4, 4), 10) == "WHEAT"
    assert exe._crop_for_tile((5, 0), 10) == "CARROT"
    assert exe._crop_for_tile((9, 4), 10) == "CARROT"
    off = Executor(Config(**H4))
    assert off._crop_for_tile((5, 0), 10) == "WHEAT"
    assert off._extra_crop() == ""


def test_h4_actions_unchanged_when_extra_crop_empty():
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    a = Executor(Config(**H4))
    b = Executor(Config(**dict(H4, extra_crop="")))
    idle = {"farmer": ["PASS"], "hands": [["PASS"]] * 6, "market": []}
    for _ in range(48):
        obs = env.state[0].observation
        n_hands = len(obs["farms"][0]["hands"])
        idle = {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}
        aa, bb = a(obs, env.configuration), b(obs, env.configuration)
        assert aa == bb
        env.step([aa, idle])


def _animals(obs, player=0):
    out = []
    tiles = obs["farms"][player]["tiles"]
    for y, row in enumerate(tiles):
        for x, t in enumerate(row):
            if isinstance(t, dict) and t.get("animal"):
                out.append((t["animal"], x, y, quadrant_of(x, y, len(tiles))))
    return out


def test_c1_pins_livestock_and_plants_carrot_off_nw():
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    exe = Executor(Config(**C1))
    planted_carrot = False
    bought_carrot = False
    bought_land = False
    nw_wheat_plant = False
    pinned = None
    orphaned = False
    while not env.done:
        obs = env.state[0].observation
        n_hands = len(obs["farms"][0]["hands"])
        idle = {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}
        action = exe(obs, env.configuration)
        if any(o and o[0] == "BUY_LAND" for o in action.get("market") or []):
            bought_land = True
            pinned = {(x, y) for _, x, y, _ in _animals(obs)}
        if any(o and o[0] == "BUY_SEED" and o[1] == "CARROT"
               for o in action.get("market") or []):
            bought_carrot = True
        acts = [action["farmer"]] + list(action.get("hands") or [])
        for act in acts:
            if act and act[0] == "PLANT" and act[1] == "CARROT":
                planted_carrot = True
            if act and act[0] == "PLANT" and act[1] == "WHEAT":
                nw_wheat_plant = True
        if pinned:
            here = {(x, y) for _, x, y, _ in _animals(obs)}
            if not pinned <= here:
                orphaned = True
        env.step([action, idle])
        if obs["day"] > 10:
            break
    assert bought_land, "C1 should buy NE land"
    assert bought_carrot, "C1 should buy carrot seed"
    assert planted_carrot, "C1 should plant carrot"
    assert nw_wheat_plant, "C1 must keep planting wheat on NW"
    assert not orphaned, "animals present at BUY_LAND must keep those tiles"


def test_c1_layout_keeps_nw_wheat_tiles():
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    exe = Executor(Config(**C1))
    idle = {"farmer": ["PASS"], "hands": [["PASS"]] * 6, "market": []}
    nw_crop = other_crop = None
    while not env.done:
        obs = env.state[0].observation
        n_hands = len(obs["farms"][0]["hands"])
        idle = {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}
        action = exe(obs, env.configuration)
        w = World(obs, env.configuration)
        slots, crop_tiles = exe._layout(w)
        if len(w.owned) >= 50:
            nw_crop = sum(1 for p in crop_tiles if quadrant_of(p[0], p[1], w.board) == "NW")
            other_crop = len(crop_tiles) - nw_crop
            break
        env.step([action, idle])
        if obs["day"] > 12:
            break
    assert nw_crop is not None and nw_crop >= 19, nw_crop
    assert other_crop >= 5, other_crop


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
