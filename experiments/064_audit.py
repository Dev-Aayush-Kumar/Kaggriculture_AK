"""E64 - Phase 15 economic audit. No strategy change.

Reads E50 H4 vs P1-S traces and engine tables. Ranks additive opportunities.
Does not modify H4 or P1-S.
"""

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.econ.tables import (  # noqa: E402
    BUYABLE_PRODUCTS, LAND_PRICES, PRODUCTS, TOWN_CENTER_PRODUCTS,
    cumulative_hire_cost,
)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
E50 = os.path.join(ROOT, "results", "e50-h4-p1s-20260824-041910.json")

ITEMS = list(PRODUCTS)


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def seats(recs, name):
    return [(r, s, r["players"][s]) for r in recs for s in (0, 1)
            if r["players"][s]["name"] == name]


def main():
    print("E64 Phase 15 audit\n")
    print("FACT  sellable:", ITEMS)
    print("FACT  buyable products:", BUYABLE_PRODUCTS)
    print("FACT  land:", LAND_PRICES)
    print("FACT  fertilizer not in town drain:", "FERTILIZER" not in TOWN_CENTER_PRODUCTS)
    print("FACT  shops do not consume fertilizer")
    print("FACT  hire 6/day cost", cumulative_hire_cost(6),
          "hire 8/day cost", cumulative_hire_cost(8),
          "delta/day", cumulative_hire_cost(8) - cumulative_hire_cost(6))
    print("FACT  CARE last-two-days worthless (tests/test_mechanics + README)")
    print("FACT  BUY/SELL same-tick round trip on one curve nets ~0")
    recs = json.load(open(E50, encoding="utf-8"))
    rows = seats(recs, "H4")
    print(f"\nFACT  E50 H4 n={len(rows)}")
    print("  zero-rev products: CARROT TOMATO STRAWBERRY MELON EGG")
    for it in ITEMS:
        rev = fmean(p.get("sell_revenue", {}).get(it, 0) for _, _, p in rows)
        har = fmean(p.get("harvested", {}).get(it, 0) for _, _, p in rows)
        sold = fmean(p.get("sell_requested", {}).get(it, 0) for _, _, p in rows)
        if rev or har or sold:
            print(f"  {it:<12} rev={rev:8.0f} h={har:6.1f} sold={sold:6.1f}")
    print("  drought_plants", round(fmean(p.get("drought_deaths", 0) for _, _, p in rows), 2),
          "decay", round(fmean(p.get("decay_deaths", 0) for _, _, p in rows), 2),
          "escapes", round(fmean(p.get("animals_escaped", 0) for _, _, p in rows), 2),
          "overflow", round(fmean(p.get("shed_overflow", 0) for _, _, p in rows), 2))
    print("  fert_col", round(fmean(p.get("fertilizer_collected", 0) for _, _, p in rows), 1),
          "idle_share", round(fmean(p.get("category_share", {}).get("idle", 0) for _, _, p in rows), 3),
          "hires", round(fmean(p.get("hires", 0) for _, _, p in rows), 1))
    print("  wheat $1-floor", round(fmean(p.get("sell_floor_units", {}).get("WHEAT", 0) for _, _, p in rows), 1),
          "wool $1-floor", round(fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows), 1))

    print("""
RANKED OPPORTUNITIES (DERIVED from E50 + engine + Phase 14)

1. Extra crew on the EXISTING H4 farm (hands_per_day=8)  << SELECTED
   Mechanism: two more hands, same 19 wheat tiles + 6 livestock slots.
   Why missed: H4 freezes crew at 6; E3 swept crew on a goose farm vs starter, not H4.
   Upside: cut drought (~2), late escape (~1), shed overflow (~3).
   Actions: Config only. Labor +1440 unit-turns. Cash +$34/day (~$1020/season).
   Wheat/livestock risk: low (no new tiles). p10: extra cost is small vs $32k tail.
   Complexity: trivial. Additive: yes (dual of Phase 14's extra-tiles failure).
   Confidence: medium. Expected P(win): small-to-moderate vs H4.

2. Fertilizer inventory support (BUY_PRODUCT FERTILIZER when glut)
   Zero field labor. Fertilizer has no town drain, so a clone also benefits
   from the higher quote. High risk vs H4 clone. Skip this phase.

3. Wheat buy/hold/sell after town drain
   Zero field labor. E50 wheat floor=0 and avg sale > base: no crash to harvest.
   Closed-adjacent to feed-buffer / wheat-churn work. Skip.

4. Skip worthless late CARE (last two days)
   ~12 actions. Too small vs $5k bar. Skip unless crew screen is mixed.

5. Unused crop/egg/land markets
   Phase 14 C1: carrots made $4.8k and still went 0-16 by stealing labor.
   Do not reopen extra-land crops. Goose/egg is livestock scaling (closed).

NOT selected: sale_qty, hold-full, extra carrot, more animals, feed rewrite.
""")


if __name__ == "__main__":
    main()
