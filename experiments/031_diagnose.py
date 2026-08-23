"""E31 - classify P1-S milk/wool $1-floor sales from real-engine traces.

8 seeds, both seats, P1-S vs P1 (contested same-family). No strategy change.
Each SELL is labelled from the existing quote-time walk plus day/quote.
"""

import os
import statistics
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.econ.tables import MARKET_PARAMS, PRICE_FLOOR  # noqa: E402

SEEDS = range(8)
LAST_DAY = 29
FLOOR_FRAC = 0.30


def classify(ev):
    """Label one quote-time sale. Floor units are the $1 tail of that lot."""
    if ev.get("floor", 0) <= 0:
        return "healthy"
    base = MARKET_PARAMS[ev["item"]]["base"]
    last = ev["day"] >= LAST_DAY
    already = ev["quote"] <= PRICE_FLOOR
    poor = ev["quote"] < base * FLOOR_FRAC
    if last and already:
        return "last_day_already_floor"
    if last and poor:
        return "last_day_poor_forced"
    if last:
        return "last_day_lot_walk"
    if already:
        return "mid_already_floor"
    if poor:
        return "mid_poor_forced"
    return "mid_lot_walk"


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def analyze(records, label):
    modes = Counter()
    units = defaultdict(lambda: Counter())
    lost = defaultdict(lambda: Counter())
    harvest = Counter()
    sold = Counter()
    floor = Counter()
    last_h = Counter()
    last_s = Counter()
    n = 0
    for _r, _s, p in seats(records, label):
        n += 1
        for item in ("MILK", "WOOL"):
            harvest[item] += p.get("harvested", {}).get(item, 0)
            sold[item] += p.get("sell_requested", {}).get(item, 0)
            floor[item] += p.get("sell_floor_units", {}).get(item, 0)
            by_h = p.get("harvest_by_day", {}).get(item) or {}
            last_h[item] += sum(q for d, q in by_h.items() if int(d) >= LAST_DAY)
        for ev in p.get("sell_events") or []:
            mode = classify(ev)
            modes[mode] += 1
            units[mode][ev["item"]] += ev["floor"] if ev["floor"] else 0
            if ev["floor"]:
                base = MARKET_PARAMS[ev["item"]]["base"]
                lost[mode][ev["item"]] += ev["floor"] * max(0, base * FLOOR_FRAC - PRICE_FLOOR)
            if ev["item"] in ("MILK", "WOOL") and ev["day"] >= LAST_DAY:
                last_s[ev["item"]] += ev["qty"]
    print(f"\n{label} seats={n}")
    print(f"  harvested milk/wool={harvest['MILK']/n:.1f}/{harvest['WOOL']/n:.1f}")
    print(f"  sold milk/wool={sold['MILK']/n:.1f}/{sold['WOOL']/n:.1f}")
    print(f"  floor milk/wool={floor['MILK']/n:.1f}/{floor['WOOL']/n:.1f}")
    print(f"  last-day harvest m/w={last_h['MILK']/n:.1f}/{last_h['WOOL']/n:.1f}")
    print(f"  last-day sold m/w={last_s['MILK']/n:.1f}/{last_s['WOOL']/n:.1f}")
    print(f"{'mode':<26}{'n':>6}{'milk $1':>10}{'wool $1':>10}{'est lost':>12}")
    wool_floor = floor["WOOL"] or 1
    for mode, c in modes.most_common():
        m = units[mode]["MILK"]
        w = units[mode]["WOOL"]
        est = lost[mode]["MILK"] + lost[mode]["WOOL"]
        print(f"{mode:<26}{c:>6}{m/n:>10.1f}{w/n:>10.1f}{est/n:>12.0f}  "
              f"wool%={100 * w / wool_floor:.0f}")
    return {"floor": floor, "modes": modes, "units": units, "n": n}


def main():
    jobs = H.build_jobs(H.spec("P1S", **B.P1_S), H.spec("P1", **B.P1),
                        SEEDS, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E31 diagnose: P1-S vs P1, {len(SEEDS)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e31-diagnose")
    analyze(records, "P1S")
    analyze(records, "P1")
    print(f"\nraw records: {base}.json")


if __name__ == "__main__":
    main()
