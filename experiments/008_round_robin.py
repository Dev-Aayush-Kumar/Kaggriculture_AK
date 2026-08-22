"""Step 7b - round-robin among the families that survived the screen.

The screen measured everyone against a single goose/wheat reference, which
cannot separate "this is a strong economy" from "this beats geese and wheat
specifically". Product prices are a shared resource: a family that sells into
markets the reference is not touching gets uncontested prices, and that
advantage evaporates once the opponent is doing the same thing.

So every contender now plays every other contender, on the same seeds, in both
seat orders. Reported per pairing (who beats whom) and overall.
"""

import itertools
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SEEDS = range(8)
DEFAULTS = dict(routing="zone_nearest", hands_per_day=6)

# The screen's three winners, plus the reference they beat, as a control.
CONTENDERS = {
    "B_cow_sheep":    dict(geese=0, cows=3, sheep=3, crops=("WHEAT",)),
    "A_diversified":  dict(geese=2, cows=2, sheep=2, crops=("WHEAT",)),
    "D_premium_crop": dict(geese=0, crops=("STRAWBERRY", "MELON"), hands_per_day=8),
    "C_goose_wheat":  dict(geese=4, crops=("WHEAT",)),
}


def spec_for(label):
    params = dict(DEFAULTS)
    params.update(CONTENDERS[label])
    return H.spec(label, **params)


def seats_of(records, label):
    """Every seat `label` held, as (record, seat_index, player_stats)."""
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def main():
    pairings = list(itertools.combinations(CONTENDERS, 2))
    jobs = []
    for a, b in pairings:
        jobs += H.build_jobs(spec_for(a), spec_for(b), SEEDS)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 12 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"round-robin: {len(pairings)} pairings x {len(SEEDS)} seeds x 2 seats "
          f"= {len(jobs)} episodes\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "round-robin")

    # ---- head-to-head grid
    names = list(CONTENDERS)
    h2h = defaultdict(lambda: [0, 0, 0])          # (a, b) -> wins, losses, ties
    for rec in records:
        a, b = rec["players"][0]["name"], rec["players"][1]["name"]
        if rec["winner"] is None:
            h2h[(a, b)][2] += 1
            h2h[(b, a)][2] += 1
        else:
            win = rec["players"][rec["winner"]]["name"]
            lose = b if win == a else a
            h2h[(win, lose)][0] += 1
            h2h[(lose, win)][1] += 1

    width = max(len(n) for n in names) + 2
    print("\nhead-to-head win rate (row beats column)\n")
    print(" " * width + "".join(f"{n[:13]:>15}" for n in names))
    for a in names:
        cells = []
        for b in names:
            if a == b:
                cells.append(f"{'-':>15}")
                continue
            w, l, t = h2h[(a, b)]
            n = w + l + t
            cells.append(f"{w}-{l}-{t} ({w / n:.2f})".rjust(15) if n else " " * 15)
        print(f"{a:<{width}}" + "".join(cells))

    # ---- overall
    header = (f"\n{'family':<16}{'n':>4}{'wins':>6}{'winrate':>9}{'money':>9}"
              f"{'median':>9}{'p10':>8}{'p90':>8}{'margin':>9}{'lost':>6}{'unsold':>8}")
    print(header)
    print("-" * len(header.strip()))
    rows = []
    for label in names:
        seats = seats_of(records, label)
        n = len(seats)
        money = sorted(r["money"][s] for r, s, _ in seats)
        wins = sum(1 for r, s, _ in seats if r["winner"] == s)

        def mean(fn, _seats=seats):
            return statistics.fmean(fn(r, s, p) for r, s, p in _seats)

        rows.append({
            "label": label, "n": n, "wins": wins, "rate": wins / n,
            "money": money,
            "margin": mean(lambda r, s, p: r["money"][s] - r["money"][1 - s]),
            "lost": mean(lambda r, s, p: p["drought_deaths"] + p["decay_deaths"]
                         + p["animals_escaped"]),
            "unsold": mean(lambda r, s, p: p["unsold_units"]),
        })

    for r in sorted(rows, key=lambda x: x["rate"], reverse=True):
        money = r["money"]
        n = r["n"]
        print(f"{r['label']:<16}{n:>4}{r['wins']:>6}{r['rate']:>9.2f}"
              f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
              f"{money[max(0, int(0.1 * n) - 1)]:>8,.0f}"
              f"{money[min(n - 1, int(0.9 * n))]:>8,.0f}"
              f"{r['margin']:>+9,.0f}{r['lost']:>6.1f}{r['unsold']:>8.1f}")

    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    errs = sum(p["n_errors"] for r in records for p in r["players"])
    print(f"\nbad statuses: {bad or 'none'}   agent exceptions: {errs}")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
