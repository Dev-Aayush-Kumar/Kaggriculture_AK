"""Probe the real engine to confirm the mechanics the strategy depends on.

Each probe drives a scripted farmer through env.step() and reports what the engine
actually did, next to what the Phase-1 analysis predicted.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kaggle_environments import make  # noqa: E402


def new_env(steps):
    return make("kaggriculture", configuration={"episodeSteps": steps, "seed": 12345},
                debug=False)


class Script:
    """Drives player 0 with a callback; player 1 always passes."""

    def __init__(self, steps):
        self.env = new_env(steps)
        self.env.reset(num_agents=2)
        self.steps = steps
        self.turn_times = []

    def obs(self):
        return self.env.state[0].observation

    def run(self, policy):
        idle = {"farmer": ["PASS"], "hands": [], "market": []}
        for _ in range(self.steps - 1):
            o = self.obs()
            t0 = time.perf_counter()
            action = policy(o)
            self.turn_times.append(time.perf_counter() - t0)
            self.env.step([action, idle])
            if self.env.done:
                break
        return self.obs()


def tile_at(o, x, y, player=0):
    return o["farms"][player]["tiles"][y][x]


# --------------------------------------------------------------------- probe 1
def probe_goose_care(care: bool, days=27):
    """Total eggs harvested from one goose at (4,4). Predicted: 48 with CARE, 23 without."""
    s = Script(days * 24)
    state = {"eggs": 0, "fert": 0, "placed": False}

    def policy(o):
        day, hour = o["day"], o["hour"]
        priv = o["private"]
        inv = priv["inventories"][0] if priv["inventories"] else {}
        shed = priv["shed"]
        tile = tile_at(o, 4, 4)
        market = []

        # sell what we accumulate so the shed never fills
        for item in ("EGG", "FERTILIZER"):
            if shed.get(item, 0) > 0:
                market.append(["SELL", item, shed[item]])
        # keep a wheat buffer in the shed
        if shed.get("WHEAT", 0) + inv.get("WHEAT", 0) < 6:
            market.append(["BUY_PRODUCT", "WHEAT", 6])

        # --- setup
        if day == 0:
            if hour == 0:
                return {"farmer": ["BUILD_COOP"], "hands": [],
                        "market": [["BUY_ANIMAL", "GOOSE", 1]] + market}
            if hour == 1:
                return {"farmer": ["PICKUP", "GOOSE", 1], "hands": [], "market": market}
            if hour == 2:
                state["placed"] = True
                return {"farmer": ["PLACE", "GOOSE"], "hands": [], "market": market}

        if not isinstance(tile, dict) or "animal" not in tile:
            return {"farmer": ["PASS"], "hands": [], "market": market}

        # --- daily husbandry: pick up feed, feed, care, harvest, collect fertilizer
        if inv.get("WHEAT", 0) < 1 and shed.get("WHEAT", 0) > 0:
            return {"farmer": ["PICKUP", "WHEAT", 3], "hands": [], "market": market}
        if not tile["fed_today"]:
            return {"farmer": ["FEED"], "hands": [], "market": market}
        if care and not tile["cared_today"]:
            return {"farmer": ["CARE"], "hands": [], "market": market}
        if tile["yield_units"] > 0:
            state["eggs"] += tile["yield_units"]
            return {"farmer": ["HARVEST"], "hands": [], "market": market}
        if tile["fertilizer_available"]:
            state["fert"] += 1
            return {"farmer": ["COLLECT_FERTILIZER"], "hands": [], "market": market}
        if inv:
            return {"farmer": ["DROP"], "hands": [], "market": market}
        return {"farmer": ["PASS"], "hands": [], "market": market}

    s.run(policy)
    return state["eggs"], state["fert"], s.turn_times


# --------------------------------------------------------------------- probe 2
def probe_watering(interval, crop="TOMATO", days=16):
    """Does watering every `interval` days keep a plant alive? Predicted: alive at 2, dead at 3."""
    s = Script(days * 24)
    log = {"died_day": None, "harvested": 0}

    def policy(o):
        day, hour = o["day"], o["hour"]
        priv, tile = o["private"], tile_at(o, 4, 4)
        market = []
        if priv["shed"].get(crop, 0) > 0:
            market.append(["SELL", crop, priv["shed"][crop]])
        if priv["seeds"].get(crop, 0) == 0 and tile is None:
            market.append(["BUY_SEED", crop, 1])

        if isinstance(tile, dict) and tile.get("kind") == "WEED" and log["died_day"] is None:
            log["died_day"] = day
        if tile is None and priv["seeds"].get(crop, 0) > 0 and day == 0:
            return {"farmer": ["PLANT", crop], "hands": [], "market": market}
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            if tile["yield_units"] > 0:
                log["harvested"] += tile["yield_units"]
                return {"farmer": ["HARVEST"], "hands": [], "market": market}
            if day % interval == 0 and not tile["watered_today"]:
                return {"farmer": ["WATER"], "hands": [], "market": market}
        if priv["inventories"] and priv["inventories"][0]:
            return {"farmer": ["DROP"], "hands": [], "market": market}
        return {"farmer": ["PASS"], "hands": [], "market": market}

    s.run(policy)
    return log


# --------------------------------------------------------------------- probe 3
def probe_hire_and_spawn():
    """Where do hands spawn, and what does hiring 12 in one turn cost?
    Predicted: cumulative fib cost 376, spawn on the four shed-access tiles."""
    s = Script(48)
    snap = {}

    def policy(o):
        if o["hour"] == 0 and o["day"] == 0:
            return {"farmer": ["PASS"], "hands": [], "market": [["HIRE"]] * 10}
        if o["hour"] == 1 and o["day"] == 0:
            n = len(o["farms"][0]["hands"])
            return {"farmer": ["PASS"], "hands": [["PASS"]] * n, "market": [["HIRE"]] * 2}
        # hands and hires_today are wiped at end of day, so snapshot mid-day
        if o["day"] == 0 and o["hour"] == 2 and not snap:
            snap["money"] = o["farms"][0]["money"]
            snap["hands"] = list(o["farms"][0]["hands"])
            snap["hires"] = o["farms"][0]["hires_today"]
            snap["farmer"] = list(o["farms"][0]["farmer"])
        n = len(o["farms"][0]["hands"])
        return {"farmer": ["PASS"], "hands": [["PASS"]] * n, "market": []}

    s.run(policy)
    return snap


# --------------------------------------------------------------------- probe 4
def probe_plant_atomicity():
    """With 1 seed and 2 PLANT requests, does the engine drop both?
    Predicted: yes -- both become PASS, seed unspent."""
    s = Script(48)
    result = {}

    def policy(o):
        day, hour = o["day"], o["hour"]
        if day == 0 and hour == 0:
            return {"farmer": ["PASS"], "hands": [], "market": [["HIRE"], ["BUY_SEED", "WHEAT", 1]]}
        if day == 0 and hour == 1:
            # farmer and one hand both try to plant the single wheat seed
            return {"farmer": ["PLANT", "WHEAT"], "hands": [["PLANT", "WHEAT"]], "market": []}
        if day == 0 and hour == 2:
            result["seeds_left"] = o["private"]["seeds"].get("WHEAT", 0)
            result["planted"] = sum(
                1 for row in o["farms"][0]["tiles"] for t in row
                if isinstance(t, dict) and t.get("kind") == "PLANT")
        n = len(o["farms"][0]["hands"])
        return {"farmer": ["PASS"], "hands": [["PASS"]] * n, "market": []}

    s.run(policy)
    return result


if __name__ == "__main__":
    print("=" * 78)
    print("PROBE 1 - CARE multiplier on a goose (27 days)")
    print("=" * 78)
    for care in (True, False):
        eggs, fert, times = probe_goose_care(care)
        label = "feed + CARE daily" if care else "feed daily, no CARE"
        pred = 48 if care else 23
        print(f"  {label:<22} eggs={eggs:>3}  (predicted ~{pred})   fertilizer={fert:>3}")
    print(f"  per-turn policy time: mean {sum(times)/len(times)*1000:.3f} ms  "
          f"max {max(times)*1000:.3f} ms")

    print()
    print("=" * 78)
    print("PROBE 2 - watering interval survival (unfertilized TOMATO)")
    print("=" * 78)
    for interval in (1, 2, 3):
        log = probe_watering(interval)
        status = "SURVIVED" if log["died_day"] is None else f"died day {log['died_day']}"
        print(f"  water every {interval} day(s): {status:<14} harvested={log['harvested']}")

    print()
    print("=" * 78)
    print("PROBE 3 - hiring cost and hand spawn positions")
    print("=" * 78)
    snap = probe_hire_and_spawn()
    print(f"  hires_today={snap['hires']}  money={snap['money']:.0f}  "
          f"(3000 - 376 = 2624 predicted)")
    print(f"  farmer at {snap['farmer']}, {len(snap['hands'])} hands at:")
    from collections import Counter
    for pos, n in sorted(Counter(tuple(h) for h in snap["hands"]).items()):
        print(f"    {pos}: {n} hand(s)")

    print()
    print("=" * 78)
    print("PROBE 4 - atomic PLANT validation")
    print("=" * 78)
    r = probe_plant_atomicity()
    print(f"  after 2 PLANT requests with 1 seed: seeds_left={r.get('seeds_left')} "
          f"tiles_planted={r.get('planted')}   (predicted 1 and 0)")
