"""E23 - three-way causal isolation: P1 vs P1-S vs QD.

Same 32 seeds, both seats, every distinct pairing. P1-S is P1 plus
sell_defer only. QD is P1-S plus sale_qty_floor=0.15.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402

SEEDS = range(32)
CHAMPS = {"P1": B.P1, "P1S": B.P1_S, "QD": B.QD}
PAIRINGS = (("P1S", "P1"), ("QD", "P1S"), ("QD", "P1"))


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


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


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
    milk_h = fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows)
    wool_h = fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_s = fmean(p.get("sell_requested", {}).get("MILK", 0) for _, _, p in rows)
    wool_s = fmean(p.get("sell_requested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold_m = fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    animals = fmean(p.get("animal_count", 0) for _, _, p in rows)
    move = fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    lost = fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                 for _, _, p in rows)
    wall = fmean(r["wall_seconds"] for r, _, _ in rows)
    print(f"{title:<16}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  milk h/s/rev/px/floor={milk_h:.1f}/{milk_s:.1f}/{milk_r:,.0f}/"
          f"{(milk_r / milk_s) if milk_s else 0:.1f}/{milk_f:.1f}"
          f"  wool={wool_h:.1f}/{wool_s:.1f}/{wool_r:,.0f}/"
          f"{(wool_r / wool_s) if wool_s else 0:.1f}/{wool_f:.1f}")
    print(f"  unsold m/w={unsold_m:.1f}/{unsold_w:.1f} animals={animals:.2f}"
          f"  move={move:.3f} idle={idle:.3f} lost={lost:.2f} wall={wall:.1f}s")
    return {
        "label": label, "wins": wins, "losses": losses, "ties": ties,
        "rate": wins / n, "mean": statistics.fmean(money),
        "median": statistics.median(money), "p10": pct(money, 0.10),
        "p25": pct(money, 0.25),
    }


def main():
    jobs = []
    for a, b in PAIRINGS:
        jobs += H.build_jobs(spec_for(a), spec_for(b), SEEDS, both_orders=True)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 16 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E23 three-way: {len(PAIRINGS)} pairings x {len(SEEDS)} "
          f"seeds x 2 seats = {len(jobs)}\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e23-controls")

    header = (f"{'matchup':<16}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
              f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
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
