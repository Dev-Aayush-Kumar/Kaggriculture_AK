"""E35 - classify H1's residual $1 wool from real-engine traces.

8 seeds, both seats, H1 vs P1-S. No strategy change. Sale modes reuse the
E31 labels; harvest events mark full-tile rescues separately so the two
causes are not collapsed.
"""

import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.econ.tables import MARKET_PARAMS, PRICE_FLOOR  # noqa: E402

SEEDS = range(8)
H1 = dict(B.P1_S, harvest_defer_enabled=True)


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def analyze(records, label):
    modes = Counter()
    units = defaultdict(lambda: Counter())
    lost = defaultdict(lambda: Counter())
    bypass = Counter()
    dropped = Counter()
    harvest = Counter()
    rescue = Counter()
    rescue_qty = Counter()
    floor = Counter()
    n = 0
    sample = []
    for _r, _s, p in seats(records, label):
        n += 1
        for item in ("MILK", "WOOL"):
            harvest[item] += p.get("harvested", {}).get(item, 0)
            floor[item] += p.get("sell_floor_units", {}).get(item, 0)
        for hv in p.get("harvest_events") or []:
            if hv["item"] in ("MILK", "WOOL") and H.harvest_is_rescue(hv):
                rescue[hv["item"]] += 1
                rescue_qty[hv["item"]] += hv["qty"]
        for ev in p.get("sell_events") or []:
            if ev.get("floor", 0) <= 0:
                continue
            mode = H.classify_floor_sale(ev)
            modes[mode] += 1
            units[mode][ev["item"]] += ev["floor"]
            base = MARKET_PARAMS[ev["item"]]["base"]
            lost[mode][ev["item"]] += ev["floor"] * max(0, base * H.FLOOR_FRAC - PRICE_FLOOR)
            why = H.sell_defer_bypass(ev)
            if why:
                bypass[why] += ev["floor"] if ev["item"] == "WOOL" else 0
            if ev.get("dropped") and ev["item"] == "WOOL":
                dropped["same_turn_drop"] += ev["floor"]
            if ev["item"] == "WOOL" and ev["floor"] > 0 and len(sample) < 12:
                sample.append({
                    "mode": mode, "day": ev["day"], "hour": ev["hour"],
                    "qty": ev["qty"], "floor": ev["floor"],
                    "quote": ev.get("quote"), "inv": ev.get("inv"),
                    "inv_after": ev.get("inv_after"),
                    "shed": ev.get("shed_used"), "item_shed": ev.get("item_shed"),
                    "on_tile": ev.get("on_tile"), "on_full": ev.get("on_full"),
                    "bypass": why, "dropped": ev.get("dropped"),
                })

    print(f"\n{label} seats={n}")
    print(f"  harvested milk/wool={harvest['MILK']/n:.1f}/{harvest['WOOL']/n:.1f}")
    print(f"  floor milk/wool={floor['MILK']/n:.1f}/{floor['WOOL']/n:.1f}")
    print(f"  rescue harvests milk/wool={rescue['MILK']/n:.1f}/{rescue['WOOL']/n:.1f}"
          f"  qty={rescue_qty['MILK']/n:.1f}/{rescue_qty['WOOL']/n:.1f}")
    print(f"{'mode':<26}{'n':>6}{'milk $1':>10}{'wool $1':>10}{'est lost':>12}")
    wool_floor = floor["WOOL"] or 1
    for mode, c in modes.most_common():
        m = units[mode]["MILK"]
        w = units[mode]["WOOL"]
        est = lost[mode]["MILK"] + lost[mode]["WOOL"]
        print(f"{mode:<26}{c:>6}{m/n:>10.1f}{w/n:>10.1f}{est/n:>12.0f}  "
              f"wool%={100 * w / wool_floor:.0f}")
    print("  sell-defer bypass wool $1:",
          {k: round(v / n, 1) for k, v in bypass.items()} or "none")
    print("  same-turn DROP wool $1:",
          round(dropped["same_turn_drop"] / n, 1))
    print("  sample $1 wool sales:")
    for row in sample:
        print(f"    {row}")
    return {
        "n": n, "floor": dict(floor), "modes": dict(modes),
        "wool_units": {k: units[k]["WOOL"] / n for k in units},
        "rescue_wool_qty": rescue_qty["WOOL"] / n,
    }


def main():
    jobs = H.build_jobs(H.spec("H1", **H1), H.spec("P1S", **B.P1_S),
                        SEEDS, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E35 residual: H1 vs P1-S, {len(SEEDS)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e35-residual")
    analyze(records, "H1")
    analyze(records, "P1S")
    print(f"\nraw records: {base}.json")


if __name__ == "__main__":
    main()
