"""E12 - champion tournament: B0 vs B1 vs B2.

B0 is the incumbent 3+3 cow/sheep Config.
B1 is the strongest scale challenger from E10 (2+2), which lost to B0 on P(win).
B2 is B0 with the market-aware livestock cap enabled.

32 seeds, both seat orders on every distinct pairing. Identical-agent mirrors
are not run; E9 already measured B0 vs B0, and E10 measured B1 vs B1.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SEEDS = range(32)
BASE = dict(routing="zone_nearest", geese=0, crops=("WHEAT",), hands_per_day=6)

CHAMPS = {
    "B0": dict(BASE, cows=3, sheep=3),
    "B1": dict(BASE, cows=2, sheep=2),
    "B2": dict(BASE, cows=3, sheep=3, livestock_cap_enabled=True),
}

PAIRINGS = (("B0", "B1"), ("B0", "B2"), ("B1", "B2"))


def spec_for(label):
    return H.spec(label, **CHAMPS[label])


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    if not n:
        print(f"{title:<16} n=0")
        return None
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    margins = [r["money"][s] - r["money"][1 - s] for r, s, _ in rows]
    milk_r = statistics.fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = statistics.fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = statistics.fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = statistics.fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    move = statistics.fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = statistics.fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    lost = statistics.fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                            for _, _, p in rows)
    unsold = statistics.fmean(p["unsold_units"] for _, _, p in rows)
    print(f"{title:<16}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}"
          f"{statistics.fmean(margins):>+9,.0f}")
    print(f"  milk rev/floor={milk_r:,.0f}/{milk_f:.1f}  wool={wool_r:,.0f}/{wool_f:.1f}"
          f"  move={move:.3f} idle={idle:.3f} lost={lost:.2f} unsold={unsold:.1f}")
    return {"label": label, "wins": wins, "losses": losses, "ties": ties,
            "rate": wins / n, "mean": statistics.fmean(money),
            "p10": pct(money, 0.10), "median": statistics.median(money)}


def main():
    jobs = []
    for a, b in PAIRINGS:
        jobs += H.build_jobs(spec_for(a), spec_for(b), SEEDS, both_orders=True)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 16 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E12 champion tournament: {len(PAIRINGS)} pairings x {len(SEEDS)} "
          f"seeds x 2 seats = {len(jobs)}\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e12-champions")

    header = (f"{'matchup':<16}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
              f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}{'margin':>9}")
    print("\n" + header)
    print("-" * len(header))
    for a, b in PAIRINGS:
        recs = [r for r in records if set(r["agents"]) == {a, b}]
        summarize(f"{a} vs {b}", recs, a)
        summarize(f"{b} vs {a}", recs, b)

    bad = [(r["seed"], r["agents"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"\nbad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
