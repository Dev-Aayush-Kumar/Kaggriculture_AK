"""Step 7 - screening tournament over candidate strategy families.

Every candidate plays the same fixed reference opponent on the same seeds in
both seat orders, so they all face the same weather, the same shop draws and the
same competing demand. This is a screen, not a verdict: the sample is small on
purpose, and it exists to decide which families deserve a real sample.

Reported for each family: win rate against the reference and the money
distribution, because P(win) is the objective but money explains it.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SEEDS = range(6)
ROUTING = "zone_nearest"

REFERENCE = H.spec("reference", routing=ROUTING, geese=4, crops=("WHEAT",),
                   hands_per_day=6)

FAMILIES = {
    "A_diversified":  dict(geese=2, cows=2, sheep=2, crops=("WHEAT",)),
    "B_cow_sheep":    dict(geese=0, cows=3, sheep=3, crops=("WHEAT",)),
    "C_goose_wheat":  dict(geese=4, crops=("WHEAT",)),
    "D_premium_crop": dict(geese=0, crops=("STRAWBERRY", "MELON"), hands_per_day=8),
    "E_crop_heavy":   dict(geese=0, crops=("WHEAT", "CARROT"), hands_per_day=10,
                           tiles_per_unit=4.0),
    "F_mixed":        dict(geese=3, crops=("WHEAT", "TOMATO")),
    "G_goose_land":   dict(geese=8, crops=("WHEAT",), hands_per_day=10, buy_land=1),
    "H_goose_max":    dict(geese=10, crops=("WHEAT",), hands_per_day=10, buy_land=2),
}

DEFAULTS = dict(routing=ROUTING, hands_per_day=6)

HEADER = (f"{'family':<16}{'n':>3}{'wins':>6}{'winrate':>9}{'money':>9}{'median':>9}"
          f"{'p10':>8}{'p90':>8}{'margin':>9}{'harv':>6}{'fert':>6}{'lost':>6}"
          f"{'unsold':>8}")


def row(records, label):
    seats = [(r, s, r["players"][s]) for r in records for s in (0, 1)
             if r["players"][s]["name"] == label]
    n = len(seats)
    money = sorted(r["money"][s] for r, s, _ in seats)
    wins = sum(1 for r, s, _ in seats if r["winner"] == s)

    def mean(fn):
        return statistics.fmean(fn(r, s, p) for r, s, p in seats)

    return (f"{label:<16}{n:>3}{wins:>6}{wins / n:>9.2f}"
            f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
            f"{money[max(0, int(0.1 * n) - 1)]:>8,.0f}"
            f"{money[min(n - 1, int(0.9 * n))]:>8,.0f}"
            f"{mean(lambda r, s, p: r['money'][s] - r['money'][1 - s]):>+9,.0f}"
            f"{mean(lambda r, s, p: p['harvested_units']):>6,.0f}"
            f"{mean(lambda r, s, p: p['fertilizer_collected']):>6,.0f}"
            f"{mean(lambda r, s, p: p['drought_deaths'] + p['decay_deaths'] + p['animals_escaped']):>6.1f}"
            f"{mean(lambda r, s, p: p['unsold_units']):>8.1f}")


def main():
    jobs = []
    for label, params in FAMILIES.items():
        merged = dict(DEFAULTS)
        merged.update(params)
        jobs += H.build_jobs(H.spec(label, **merged), REFERENCE, SEEDS)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 10 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"screening {len(FAMILIES)} families over {len(SEEDS)} seeds x 2 seats "
          f"= {len(jobs)} episodes, all vs the same reference agent\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "portfolio-screen")

    print("\n" + HEADER)
    print("-" * len(HEADER))
    for label in FAMILIES:
        print(row(records, label))
    print("-" * len(HEADER))
    print(row(records, "reference"))
    print(f"\nraw records: {base}.json")
    print("\nreference = zone_nearest, 4 geese, wheat, 6 hands. "
          "'margin' is money minus the opponent's in the same episode.")


if __name__ == "__main__":
    main()
