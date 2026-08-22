"""E14 - one movement/drop rule on top of B2.

P0 is B2 (3+3, livestock cap on, zone_nearest). P1 is the same Config plus
move_ev_enabled: idle shed walks are taken only when carried quote-value covers
min_trip_value_per_step per tile, except in the last hours of the day.

Assigned feed/water/rescue walks are not changed. 16-seed paired screen first;
expand to 32 only if P1 is directionally better on P(win) or money without a
material p10 hit.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SCREEN_SEEDS = range(16)
FINAL_SEEDS = range(32)

P0 = dict(routing="zone_nearest", geese=0, cows=3, sheep=3, crops=("WHEAT",),
          hands_per_day=6, livestock_cap_enabled=True)
P1 = dict(P0, move_ev_enabled=True)


def spec(label, params):
    return H.spec(label, **params)


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
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    move = statistics.fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = statistics.fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    prod = 1.0 - move - idle
    lost = statistics.fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                            for _, _, p in rows)
    milk_r = statistics.fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = statistics.fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = statistics.fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = statistics.fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold = statistics.fmean(p["unsold_units"] for _, _, p in rows)
    print(f"{title:<12}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  move={move:.3f} prod={prod:.3f} idle={idle:.3f} lost={lost:.2f}"
          f"  milk rev/floor={milk_r:,.0f}/{milk_f:.1f}"
          f"  wool={wool_r:,.0f}/{wool_f:.1f} unsold={unsold:.1f}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n,
        "mean": statistics.fmean(money), "p10": pct(money, 0.10),
        "median": statistics.median(money), "move": move,
    }


def promising(p1, p0):
    """Directional: more wins than losses, or better money, without a p10 hit."""
    better_record = p1["wins"] > p1["losses"]
    better_money = p1["mean"] > p0["mean"] or p1["median"] > p0["median"]
    p10_ok = p1["p10"] >= p0["p10"] * 0.97
    return (better_record or better_money) and p10_ok


def header():
    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))


def run_pair(seeds, tag):
    jobs = H.build_jobs(spec("P1", P1), spec("P0", P0), seeds, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: P1 vs P0, {len(seeds)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    header()
    p1 = summarize("P1 vs P0", records, "P1")
    p0 = summarize("P0 vs P1", records, "P0")
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")
    return p1, p0


def main():
    p1, p0 = run_pair(SCREEN_SEEDS, "e14-screen")
    if not promising(p1, p0):
        print("\nE14 screen: P1 is not a credible improvement. "
              "Movement hypothesis stops here; not expanded.")
        return
    print("\nE14 screen looks directional; expanding to 32 seeds.\n")
    run_pair(FINAL_SEEDS, "e14-finals")


if __name__ == "__main__":
    main()
