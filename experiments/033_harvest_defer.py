"""E32/E33 - harvest-defer on P1-S, targeting shed-forced poor wool sales.

H0 is unchanged P1-S. H1 skips non-full animal harvest while the product
quote is below the existing 0.30 floor. 8-seed screen, then 32 if promising.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402

SCREEN_SEEDS = range(8)
FINAL_SEEDS = range(32)

H0 = dict(B.P1_S)
H1 = dict(B.P1_S, harvest_defer_enabled=True)


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    milk_h = fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows)
    wool_h = fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold_m = fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    move = fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    lost = fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                 for _, _, p in rows)
    animals = fmean(p.get("animal_count", 0) for _, _, p in rows)
    print(f"{title:<12}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  milk h/rev/floor={milk_h:.1f}/{milk_r:,.0f}/{milk_f:.1f}"
          f"  wool={wool_h:.1f}/{wool_r:,.0f}/{wool_f:.1f}"
          f"  unsold m/w={unsold_m:.1f}/{unsold_w:.1f}")
    print(f"  animals={animals:.2f} move={move:.3f} idle={idle:.3f} lost={lost:.2f}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n,
        "mean": statistics.fmean(money), "p10": pct(money, 0.10),
        "median": statistics.median(money), "lost": lost, "wool_floor": wool_f,
    }


def promising(h1, h0):
    better_record = h1["wins"] > h1["losses"]
    better_tail = h1["p10"] > h0["p10"]
    p10_ok = h1["p10"] >= h0["p10"] * 0.97
    reliable = h1["lost"] <= h0["lost"] + 0.5
    return (better_record or better_tail) and p10_ok and reliable


def run_pair(seeds, tag):
    jobs = H.build_jobs(H.spec("H1", **H1), H.spec("H0", **H0),
                        seeds, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: H1 vs H0, {len(seeds)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))
    h1 = summarize("H1 vs H0", records, "H1")
    h0 = summarize("H0 vs H1", records, "H0")
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")
    return h1, h0


def main():
    h1, h0 = run_pair(SCREEN_SEEDS, "e33-screen")
    if not promising(h1, h0):
        print("\nE33 screen: H1 is not a credible improvement. "
              "Harvest-defer hypothesis stops here.")
        return
    print("\nE33 screen looks directional; expanding to 32 seeds.\n")
    run_pair(FINAL_SEEDS, "e33-finals")


if __name__ == "__main__":
    main()
