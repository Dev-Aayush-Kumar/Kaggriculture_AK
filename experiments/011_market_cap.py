"""E11 - smoke the market-aware livestock cap (B2) against B0.

This is a hypothesis test, not a promotion: B2 is B0 with `livestock_cap_enabled`
turned on and the default slack/floor. It must be allowed to lose.

A short paired sample measures whether the cap actually changes stocking
versus B0. The champion comparison is E12.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SEEDS = range(8)
BASE = dict(routing="zone_nearest", geese=0, cows=3, sheep=3, crops=("WHEAT",),
            hands_per_day=6)

B0 = dict(BASE)
B2 = dict(BASE, livestock_cap_enabled=True)


def spec(label, params):
    return H.spec(label, **params)


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def row(records, label):
    rows = seats(records, label)
    n = len(rows)
    money = sorted(r["money"][s] for r, s, _ in rows)
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    animals = statistics.fmean(p.get("animal_count", 0) for _, _, p in rows)
    milk = statistics.fmean(p["harvested"].get("MILK", 0) for _, _, p in rows)
    wool = statistics.fmean(p["harvested"].get("WOOL", 0) for _, _, p in rows)
    print(f"{label:<8}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{money[max(0, int(0.1 * n) - 1)]:>8,.0f}"
          f"{animals:>8.2f}{milk:>8.1f}{wool:>8.1f}")


def main():
    jobs = H.build_jobs(spec("B2", B2), spec("B0", B0), SEEDS, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E11 smoke: B2 vs B0, {len(SEEDS)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e11-b2-smoke")

    print(f"\n{'agent':<8}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
          f"{'money':>9}{'median':>9}{'p10':>8}{'animals':>8}{'milk':>8}{'wool':>8}")
    row(records, "B2")
    row(records, "B0")

    same_animals = sum(
        1 for r in records
        if r["players"][0].get("animal_count") == r["players"][1].get("animal_count")
        and abs(r["players"][0]["harvested"].get("MILK", 0)
                - r["players"][1]["harvested"].get("MILK", 0)) < 1e-6)
    print(f"\nepisodes with matching animal count and milk harvest: "
          f"{same_animals}/{len(records)}")
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
