"""E34 - field check of harvest-defer (H1) against P1-S and the existing families.

Run only because E33 beat P1-S on P(win) without L3-scale tail damage.
Smallest directional sample: 8 paired seeds, both seats. Does not rerun
historical tournaments.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402

SEEDS = range(8)
CHAMPION = "H1"
CHAMPION_PARAMS = dict(B.P1_S, harvest_defer_enabled=True)

FIELD = {
    "P1S":            dict(B.P1_S),
    "A_diversified":  dict(routing="zone_nearest", geese=2, cows=2, sheep=2,
                           crops=("WHEAT",), hands_per_day=6),
    "D_premium_crop": dict(routing="zone_nearest", geese=0,
                           crops=("STRAWBERRY", "MELON"), hands_per_day=8),
    "C_goose_wheat":  dict(routing="zone_nearest", geese=4, cows=0, sheep=0,
                           crops=("WHEAT",), hands_per_day=6),
    "reference":      dict(routing="zone_nearest", geese=4, cows=0, sheep=0,
                           crops=("WHEAT",), hands_per_day=6),
}


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


def summarize(records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    lost = fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                 for _, _, p in rows)
    print(f"{label:<16}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n if n else 0:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}"
          f"{wool_f:>8.1f}{lost:>7.2f}")


def main():
    jobs = []
    for label in FIELD:
        jobs += H.build_jobs(H.spec(CHAMPION, **CHAMPION_PARAMS),
                             H.spec(label, **FIELD[label]),
                             SEEDS, both_orders=True)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E34 field check: {CHAMPION} vs {list(FIELD)} "
          f"on {len(SEEDS)} seeds x 2 seats = {len(jobs)}\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e34-field")

    print(f"\n{'agent':<16}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
          f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'w$1':>8}{'lost':>7}")
    summarize(records, CHAMPION)
    for label in FIELD:
        summarize(records, label)

    print(f"\nper-opponent {CHAMPION} record")
    for label in FIELD:
        recs = [r for r in records if label in r["agents"]]
        rows = seats(recs, CHAMPION)
        n = len(rows)
        money = [r["money"][s] for r, s, _ in rows]
        opp_money = [r["money"][1 - s] for r, s, _ in rows]
        wins = sum(1 for r, s, _ in rows if r["winner"] == s)
        losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
        ties = n - wins - losses
        print(f"  vs {label:<16} {wins}-{losses}-{ties}"
              f"  mean {statistics.fmean(money):,.0f} vs {statistics.fmean(opp_money):,.0f}"
              f"  p10 {pct(money, 0.10):,.0f}")

    bad = [(r["seed"], r["agents"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"\nbad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
