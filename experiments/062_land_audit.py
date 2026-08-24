"""E62 - audit buy_land on frozen H4. No extra-crop change.

Confirms when $1000 NE land is affordable, how many new crop tiles the
crew cap actually opens, and whether unlocking NE reshuffles livestock
slots (the executor assigns the nearest owned tiles to animals).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import contextlib
import io

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make

import baselines as B  # noqa: E402
from kagg.agent import Executor  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.tables import LAND_PRICES, quadrant_of, shed_access_tiles  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)


def layout_snapshot(exe, obs, cfg):
    w_owned = []
    farm = obs["farms"][obs["player"]]
    tiles = farm["tiles"]
    board = len(tiles)
    animals = []
    for y, row in enumerate(tiles):
        for x, t in enumerate(row):
            if t != "LOCKED":
                w_owned.append((x, y))
            if isinstance(t, dict) and "animal" in t:
                animals.append((t["animal"], x, y, quadrant_of(x, y, board)))
    access = shed_access_tiles(board)
    def dist(p):
        return min(abs(p[0] - ax) + abs(p[1] - ay) for ax, ay in access)
    ordered = sorted(w_owned, key=lambda p: (dist(p), p[1], p[0]))
    crew = max(1, cfg.hands_per_day + 1)
    limit = min(cfg.max_crop_tiles, int(crew * cfg.tiles_per_unit))
    n_slots = cfg.cows + cfg.sheep + cfg.geese
    crop_n = min(limit, max(0, len(w_owned) - n_slots))
    nw_crop = sum(1 for p in ordered[n_slots:n_slots + crop_n]
                  if quadrant_of(p[0], p[1], board) == "NW")
    other_crop = crop_n - nw_crop
    return {
        "owned": len(w_owned), "quads": list(farm.get("unlocked_quadrants") or []),
        "animals": animals, "crop_n": crop_n, "nw_crop": nw_crop,
        "other_crop": other_crop, "limit": limit,
        "slot_quads": [quadrant_of(p[0], p[1], board) for p in ordered[:n_slots]],
    }


def main():
    print("E62 land/crop audit on H4 (no extra_crop)\n")
    cfg_h4 = Config(**H4)
    cfg_land = Config(**dict(H4, buy_land=1, tiles_per_unit=4.0))
    print(f"H4 buy_land={cfg_h4.buy_land} tiles_per_unit={cfg_h4.tiles_per_unit} "
          f"max_crop_tiles={cfg_h4.max_crop_tiles} crops={cfg_h4.crops}")
    print(f"LAND+wide tiles_per_unit={cfg_land.tiles_per_unit} "
          f"limit={min(cfg_land.max_crop_tiles, int(7 * cfg_land.tiles_per_unit))}")
    print(f"NE land cost={LAND_PRICES[0]} land_reserve={cfg_h4.land_reserve} "
          f"need_cash>={LAND_PRICES[0] + cfg_h4.land_reserve}")
    print(f"CARROT seed=20 first/max yield day 2/3 max_yield=4 ongoing=False base=35 T=450")
    print(f"TOMATO seed=50 first/max 8/8 interval=1 max_yield=4 ongoing=True base=60 T=200")
    print(f"TOMATO produces at most 4 events then sets a lifespan; not a perpetual plant.")

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 0})
    env.reset(num_agents=2)
    exe = Executor(cfg_land)
    idle = {"farmer": ["PASS"], "hands": [["PASS"]] * 6, "market": []}
    land_day = None
    prev_animal_pos = None
    shuffled = False
    while not env.done:
        obs = env.state[0].observation
        n_hands = len(obs["farms"][0]["hands"])
        idle = {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}
        action = exe(obs, env.configuration)
        snap = layout_snapshot(exe, obs, cfg_land)
        cur = tuple((a, x, y) for a, x, y, _ in snap["animals"])
        if prev_animal_pos is not None and cur and prev_animal_pos != cur:
            if land_day is not None and obs["day"] >= land_day:
                shuffled = True
        if any(o and o[0] == "BUY_LAND" for o in action.get("market") or []):
            land_day = obs["day"]
            print(f"\nBUY_LAND queued day={obs['day']} hour={obs['hour']} "
                  f"money={obs['farms'][0]['money']:.0f}")
            print(f"  owned={snap['owned']} quads={snap['quads']} "
                  f"crop_n={snap['crop_n']} nw={snap['nw_crop']} other={snap['other_crop']}")
            print(f"  planned slot quads={snap['slot_quads']}")
            print(f"  animals now={snap['animals']}")
        if obs["hour"] == 0 and obs["day"] in (0, 1, 5, 6, 7, 8, 10, 14):
            print(f"d{obs['day']} money={obs['farms'][0]['money']:.0f} "
                  f"owned={snap['owned']} crop_n={snap['crop_n']} "
                  f"nw={snap['nw_crop']} other={snap['other_crop']} "
                  f"animals={len(snap['animals'])} slots={snap['slot_quads']}")
        prev_animal_pos = cur or prev_animal_pos
        env.step([action, idle])
        if obs["day"] > 16:
            break
    print(f"\nland_day={land_day} animal_tiles_moved_after_land={shuffled}")
    print("E62: if slot quads include NE after unlock, livestock layout reshuffles.")


if __name__ == "__main__":
    main()
