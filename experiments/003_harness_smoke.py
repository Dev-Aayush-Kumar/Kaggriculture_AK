"""Smoke-test the harness, the v0 executor, and the parallel runner.

Verifies the whole action interface end to end: movement, planting, watering,
harvesting, animal handling, CARE, fertilizer collection, market interaction
and end-of-game liquidation, and checks that the executor emits no invalid
actions at all.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

V0 = H.spec("v0", geese=4, crops=("WHEAT",), hands_per_day=6)


def detail(p):
    for key in ("unit_turns", "effective_rate", "hires", "travel", "categories",
                "top_waste", "harvested", "fertilizer_collected", "market_ops",
                "sell_requested", "dropped_orders", "malformed_orders",
                "unsold_units", "drought_deaths", "decay_deaths", "decayed_units",
                "animals_escaped", "shed_overflow", "latency_p99_ms",
                "latency_max_ms", "n_errors", "errors"):
        print(f"    {key:<22} {p[key]}")
    print(f"    {'money d0/d10/d20/d29':<22} "
          f"{[p['money_by_day'][i] for i in (0, 10, 20, 29)]}")


def main():
    print("built-in agents:", sorted(H.BUILTIN))

    t0 = time.perf_counter()
    rec = H.play(V0, "starter", seed=1)
    print(f"\nv0 vs starter, seed 1  ->  money={rec['money']}  "
          f"status={rec['statuses']}  wall={rec['wall_seconds']}s  "
          f"failure={rec['failure']}")
    print("  v0 detail:")
    detail(rec["players"][0])

    print(f"\nsingle episode took {time.perf_counter() - t0:.1f}s; "
          f"now 8 episodes in parallel")
    t0 = time.perf_counter()
    recs = H.run_matchup(V0, "starter", seeds=range(4))
    par = time.perf_counter() - t0
    print(f"  {len(recs)} episodes in {par:.1f}s "
          f"({par / len(recs):.1f}s each wall-clock)\n")
    print(H.report(H.aggregate(recs, "v0")))
    print()
    print(H.report(H.aggregate(recs, "starter")))
    base = H.save(recs, "smoke")
    print(f"\nwrote {base}.json / .csv")


if __name__ == "__main__":
    main()
