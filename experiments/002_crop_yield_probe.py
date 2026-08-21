"""Verify one-time crop yields, fertilizer effect, and decay onset on the real engine."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from kaggle_environments import make

CROPS = {"WHEAT": (2, 4), "CARROT": (2, 3), "MELON": (10, 12)}   # (first_yield_day, max_yield_day)
IDLE = {"farmer": ["PASS"], "hands": [], "market": []}


def run(crop, fertilize, harvest_day=None, days=20):
    """Plant at (4,4) day 0; water to survive + every bonus-window day; harvest at
    harvest_day (default max_yield_day). Returns (units, decay_log)."""
    first, maxday = CROPS[crop]
    ws = (maxday + 1) // 2                      # bonus window start, engine formula
    hday = maxday if harvest_day is None else harvest_day
    water_days = set(range(0, ws, 2)) | set(range(ws, hday + 1))
    fert_days = set(range(ws, maxday + 1, 3)) if fertilize else set()

    env = make("kaggriculture", configuration={"episodeSteps": days * 24, "seed": 7})
    env.reset(num_agents=2)
    got = {"units": 0, "peak": 0, "decay": []}

    for _ in range(days * 24 - 1):
        o = env.state[0].observation
        day, hour = o["day"], o["hour"]
        priv, tile = o["private"], o["farms"][0]["tiles"][4][4]
        inv = priv["inventories"][0] if priv["inventories"] else {}
        mkt = []
        if priv["seeds"].get(crop, 0) == 0 and tile is None and day == 0:
            mkt.append(["BUY_SEED", crop, 1])
        if fertilize and priv["shed"].get("FERTILIZER", 0) + inv.get("FERTILIZER", 0) < 3:
            mkt.append(["BUY_PRODUCT", "FERTILIZER", 3])

        act = ["PASS"]
        if tile is None and priv["seeds"].get(crop, 0) > 0 and day == 0:
            act = ["PLANT", crop]
        elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
            got["peak"] = max(got["peak"], tile["yield_units"])
            if day > maxday:                     # observe decay instead of harvesting
                got["decay"].append((day, hour, tile["yield_units"]))
            elif day == hday and tile["yield_units"] > 0 and hour >= 20:
                got["units"] = tile["yield_units"]
                act = ["HARVEST"]
            elif day in fert_days and inv.get("FERTILIZER", 0) > 0 \
                    and tile["fertilized_until_day"] < day:
                act = ["FERTILIZE"]
            elif day in fert_days and inv.get("FERTILIZER", 0) == 0 \
                    and priv["shed"].get("FERTILIZER", 0) > 0:
                act = ["PICKUP", "FERTILIZER", 1]
            elif day in water_days and not tile["watered_today"]:
                act = ["WATER"]
        env.step([{"farmer": act, "hands": [], "market": mkt}, IDLE])
        if env.done:
            break
    return got


print("one-time crop yields (harvest at max_yield_day, optimal watering)")
print(f"{'crop':<8}{'window':>9}{'water-only':>12}{'fertilized':>12}   predicted")
pred = {"WHEAT": "4 / 6", "CARROT": "3 / 4", "MELON": "6 / 6"}
for c in CROPS:
    a = run(c, False)["units"]
    b = run(c, True)["units"]
    ws = (CROPS[c][1] + 1) // 2
    print(f"{c:<8}{f'd{ws}-d{CROPS[c][1]}':>9}{a:>12}{b:>12}   {pred[c]}")

print("\ndecay onset: WHEAT left unharvested past max_yield_day (d4)")
d = run("WHEAT", False, harvest_day=99, days=8)["decay"]
print("  first 8 observations (day, hour, yield_units):", d[:8])
print("  predicted: decay starts day 5 hour 0, -1 unit every 2 turns")
