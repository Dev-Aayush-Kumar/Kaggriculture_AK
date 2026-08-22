"""E20 - one combination check: best E19 quantity candidate plus sell-defer.

Q15 was the least-damaging sale-qty floor in E19 but lost to P1 at 32 seeds.
This run asks whether stacking the already-tested sell_defer flag is
complementary. 16 seeds, both seats, two pairings only.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402

SEEDS = range(16)
Q15 = dict(B.P1, sale_qty_enabled=True, sale_qty_floor=0.15)
QD = dict(Q15, sell_defer_enabled=True)

PAIRINGS = (("Q15", Q15, "QD", QD), ("QD", QD, "P1", B.P1))


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
    milk_f = statistics.fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = statistics.fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = statistics.fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = statistics.fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    unsold_m = statistics.fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = statistics.fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    print(f"{title:<12}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  milk/wool rev={milk_r:,.0f}/{wool_r:,.0f}  floor={milk_f:.1f}/{wool_f:.1f}"
          f"  unsold m/w={unsold_m:.1f}/{unsold_w:.1f}")
    return {"wins": wins, "losses": losses, "p10": pct(money, 0.10),
            "mean": statistics.fmean(money)}


def main():
    jobs = []
    for a, ap, b, bp in PAIRINGS:
        jobs += H.build_jobs(H.spec(a, **ap), H.spec(b, **bp), SEEDS, both_orders=True)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E20: Q15 vs QD and QD vs P1, {len(SEEDS)} seeds x 2 seats x 2 "
          f"pairings = {len(jobs)}\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e20-combo")

    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))
    for a, _ap, b, _bp in PAIRINGS:
        recs = [r for r in records if set(r["agents"]) == {a, b}]
        summarize(f"{a} vs {b}", recs, a)
        summarize(f"{b} vs {a}", recs, b)

    bad = [(r["seed"], r["agents"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"\nbad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")


def run_finals():
    """Expand QD vs P1 only; no new combination."""
    jobs = H.build_jobs(H.spec("QD", **QD), H.spec("P1", **B.P1),
                        range(32), both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"e20-finals: QD vs P1, 32 seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e20-finals")
    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))
    summarize("QD vs P1", records, "QD")
    summarize("P1 vs QD", records, "P1")
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "finals":
        run_finals()
    else:
        main()
        print("\nE20 screen was directional; expanding QD vs P1 to 32 seeds.\n")
        run_finals()

