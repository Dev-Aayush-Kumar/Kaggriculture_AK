"""E54 - identify the highest-EV remaining leak from H4 traces. No strategy change.

CSV animal_count is the final on-tile herd after the leftover escape, so it
reads 5 even when the farm did reach the configured 3+3. This diagnostic
separates that from day-0 capital: after hire and 3 cows, livestock_reserve=300
buys only 2 sheep, and the third sheep arrives around day 5-6.
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
import harness as H  # noqa: E402
from kagg.agent import Executor, remaining_yield_events  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.tables import ANIMALS, cumulative_hire_cost  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)
LAST_DAY = 29
SEEDS = range(1)


def day0_orders(params, seed=0):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.reset(num_agents=2)
    obs = env.state[0].observation
    action = Executor(Config(**params))(obs, env.configuration)
    return action["market"], float(obs["farms"][0]["money"])


def first_day_with(series, n):
    for d, v in enumerate(series or []):
        if v >= n:
            return d
    return None


def main():
    print("E54 Phase 13 leak diagnostic\n")
    cfg = Config(**H4)
    print(f"H4 livestock_reserve={cfg.livestock_reserve} cows={cfg.cows} "
          f"sheep={cfg.sheep} fertilize_crops={cfg.fertilize_crops}")
    print(f"P1-S livestock_reserve={Config(**B.P1_S).livestock_reserve}")
    assert cfg.livestock_reserve == 300
    assert Config(**B.P1_S).livestock_reserve == 300

    orders, money = day0_orders(H4)
    hire = cumulative_hire_cost(cfg.hands_per_day)
    cows = sum(o[2] for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW")
    sheep = sum(o[2] for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "SHEEP")
    print(f"\nday-0 money={money:.0f} hire={hire} after_hire={money - hire:.0f}")
    print("day-0 orders:")
    for o in orders:
        print(f"  {o}")
    print(f"day-0 buys: cows={cows} sheep={sheep}")
    after_cows = money - hire - cows * ANIMALS["COW"]["cost"]
    print(f"after 3 cows {after_cows:.0f}; "
          f"(purse-reserve)//sheep_cost = "
          f"{int((after_cows - cfg.livestock_reserve) // ANIMALS['SHEEP']['cost'])}")
    print(f"reserve 280 would buy "
          f"{int((after_cows - 280) // ANIMALS['SHEEP']['cost'])} sheep")

    d0 = remaining_yield_events("SHEEP", 0, 0, LAST_DAY)
    d5 = remaining_yield_events("SHEEP", 5, 5, LAST_DAY)
    print(f"\nsheep yield events: placed d0={d0}  placed d5={d5}  "
          f"missed={d0 - d5} (care-on units {(d0 - d5) * 2})")

    jobs = H.build_jobs(H.spec("H4", **H4), H.spec("P1S", **dict(B.P1_S)),
                        SEEDS, both_orders=True)
    print(f"\nH4 vs P1-S, {len(SEEDS)} seed x 2 = {len(jobs)}", flush=True)
    records = H.run_jobs(jobs)
    base = H.save(records, "e54-h4-p1s")
    for rec in records:
        for seat in (0, 1):
            p = rec["players"][seat]
            series = p.get("animals_by_day") or []
            sold = p.get("sell_requested") or {}
            rev = p.get("sell_revenue") or {}
            print(f"  seed {rec['seed']} seat {seat} {p['name']} "
                  f"money={rec['money'][seat]:.0f} "
                  f"final_animals={p.get('animal_count')} "
                  f"max_animals={max(series) if series else None} "
                  f"first_6={first_day_with(series, 6)} "
                  f"wheat_sold={sold.get('WHEAT', 0)} "
                  f"wheat_rev={rev.get('WHEAT', 0):.0f} "
                  f"fert_rev={rev.get('FERTILIZER', 0):.0f} "
                  f"milk_rev={rev.get('MILK', 0):.0f} "
                  f"wool_rev={rev.get('WOOL', 0):.0f}")
            print(f"    animals_by_day={series}")

    print("\nE54 FACTS")
    print("  CSV animal_count is the final herd after the leftover escape.")
    print("  Day-0 capital after hire+3 cows buys 2 sheep at reserve=300.")
    print("  The 3rd sheep is bought later (around day 5-6) and misses "
          f"{d0 - d5} wool events.")
    print("  Wheat and fertilizer are the other large quote-revenue lines; "
          "fertilize_crops remains off.")
    print("  Classification: C resource/capital timing (3rd sheep delay), "
          "with B missed crop-side fertilizer use still open.")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
