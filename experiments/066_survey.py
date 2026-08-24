"""E66 - Phase 16 diagnostic survey of frozen H4. No strategy change.

Reads E50 (64 H4 seats vs P1-S) and E53 (16 H4 seats with at-risk visits).
Prints the economic / execution surface used to rank one next experiment.
"""

import json
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import remaining_yield_events  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.tables import (  # noqa: E402
    ANIMALS, BUYABLE_PRODUCTS, MARKET_PARAMS, PRODUCTS, TOWN_CENTER_PRODUCTS,
    cumulative_hire_cost,
)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
E50 = os.path.join(ROOT, "results", "e50-h4-p1s-20260824-041910.json")
E49 = os.path.join(ROOT, "results", "e49-h4-h3-20260824-035528.json")
E53 = os.path.join(ROOT, "results", "e53-h4-p1s-20260824-194635.json")
E65 = os.path.join(ROOT, "results", "e65-h5-h4-20260824-222905.json")
E63 = os.path.join(ROOT, "results", "e63-c1-h4-20260824-221039.json")

LAST_DAY = 29
WHEAT_BASE = MARKET_PARAMS["WHEAT"]["base"]
CATS = ["move", "idle", "water", "feed", "care", "harvest", "plant",
        "fertilizer", "logistics", "wasted", "clear", "build", "fertilize"]


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def seats(recs, name):
    return [(r, s, r["players"][s]) for r in recs for s in (0, 1)
            if r["players"][s]["name"] == name]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def show_rev(rows):
    print("  product        rev       h    sold  floor  unsold   px")
    tot = 0
    for it in PRODUCTS:
        rev = fmean(p.get("sell_revenue", {}).get(it, 0) for _, _, p in rows)
        har = fmean(p.get("harvested", {}).get(it, 0) for _, _, p in rows)
        sold = fmean(p.get("sell_requested", {}).get(it, 0) for _, _, p in rows)
        fl = fmean(p.get("sell_floor_units", {}).get(it, 0) for _, _, p in rows)
        uns = fmean((p.get("final_shed") or {}).get(it, 0) for _, _, p in rows)
        tot += rev
        if rev or har or sold or uns:
            px = rev / sold if sold else 0
            print(f"  {it:<12} {rev:8.0f} {har:6.1f} {sold:7.1f} {fl:6.1f} "
                  f"{uns:7.1f} {px:6.1f}")
        else:
            print(f"  {it:<12}        0    0.0     0.0    0.0     0.0    —")
    print(f"  TOTAL quote-rev {tot:,.0f}")
    return tot


def series(rows, key, n=30):
    out = []
    for d in range(n):
        vals = []
        for _, _, p in rows:
            xs = p.get(key) or []
            if d < len(xs) and not isinstance(xs[d], dict):
                vals.append(xs[d])
        out.append(round(fmean(vals)) if vals else None)
    return out


def shed_item(rows, item, n=30):
    out = []
    for d in range(n):
        vals = []
        for _, _, p in rows:
            xs = p.get("shed_by_day") or []
            if d < len(xs) and isinstance(xs[d], dict):
                vals.append(xs[d].get(item, 0))
        out.append(fmean(vals) if vals else 0.0)
    return out


def remain_val(animal, placed_day, loss_day, quote):
    if placed_day is None or placed_day < 0:
        return None, None
    n = remaining_yield_events(animal, placed_day, loss_day + 1, LAST_DAY)
    if quote is None:
        quote = MARKET_PARAMS[ANIMALS[animal]["product"]]["base"]
    return n, n * quote


def classify_escape(ev, visits):
    n, val = remain_val(
        ev.get("animal"), ev.get("placed_day"), ev.get("loss_day", LAST_DAY),
        ev.get("quote") or ev.get("wool_quote"))
    tile_visits = [v for v in visits
                   if v.get("x") == ev.get("x") and v.get("y") == ev.get("y")
                   and v.get("day") == ev.get("loss_day")]
    feasible = []
    for v in tile_visits:
        wheat_ok = (v.get("wheat_hand") or 0) >= 1 or (v.get("wheat_shed") or 0) >= 1
        in_time = (v.get("pickup_cost") or 99) <= (v.get("hours_left") or 0)
        if wheat_ok and in_time:
            feasible.append(v)
    if not tile_visits or not feasible:
        return "A", n, val, tile_visits, feasible
    if val is None or val <= WHEAT_BASE:
        return "B", n, val, tile_visits, feasible
    return "C", n, val, tile_visits, feasible


def dump_e53(rows):
    print(f"\n======== E53 leftover visits n={len(rows)} ========")
    classes = Counter()
    a_nov = a_nowheat = a_notime = 0
    helds, rems, quotes, held_rev = [], [], [], []
    for r, s, p in rows:
        visits = p.get("at_risk_visits") or []
        for ev in p.get("escape_events") or []:
            if ev.get("loss_day", -1) < 27 and ev.get("obs_day", -1) < 28:
                continue
            cls, n, val, tvs, feas = classify_escape(ev, visits)
            classes[cls] += 1
            fv = tvs[0] if tvs else None
            q = ev.get("wool_quote") or ev.get("quote") or 0
            held = ev.get("held") or 0
            helds.append(held)
            rems.append(val or 0)
            quotes.append(q)
            held_rev.append(held * q)
            print(f"  seed {r['seed']} seat {s} {cls} {ev.get('animal')} "
                  f"@({ev.get('x')},{ev.get('y')}) held={held} remain_n={n} "
                  f"val={val} visits={len(tvs)} feas={len(feas)}")
            if fv:
                print(f"    h{fv.get('hour')} op={fv.get('op')} "
                      f"hand={fv.get('wheat_hand')} shed={fv.get('wheat_shed')} "
                      f"dist={fv.get('dist_shed')} cost={fv.get('pickup_cost')} "
                      f"left={fv.get('hours_left')}")
                no_wheat = ((fv.get("wheat_hand") or 0) < 1
                            and (fv.get("wheat_shed") or 0) < 1)
                no_time = (fv.get("pickup_cost") or 99) > (fv.get("hours_left") or 0)
                if cls == "A":
                    if no_wheat:
                        a_nowheat += 1
                    if no_time:
                        a_notime += 1
            elif cls == "A":
                a_nov += 1
    print(f"  class {dict(classes)}  A no-visit={a_nov} "
          f"A no-wheat={a_nowheat} A no-time={a_notime}")
    if helds:
        print(f"  mean held={fmean(helds):.2f} quote={fmean(quotes):.1f} "
              f"held*quote={fmean(held_rev):.0f} remain_val={fmean(rems):.0f}")
        print(f"  incremental if sheep lives (remain + 1 fert day ~$69, "
              f"held wool only if never harvested): "
              f"~${fmean(rems) + 69:.0f} to "
              f"~${fmean(rems) + 69 + fmean(held_rev):.0f}")


def main():
    print("E66 Phase 16 H4 survey (read-only)\n")
    cfg = Config()
    knobs = sorted(k for k in vars(Config)
                   if not k.startswith("_") and not callable(getattr(Config, k)))
    print("FACT  Config knobs:", ", ".join(knobs))
    print("FACT  BUYABLE_PRODUCTS", BUYABLE_PRODUCTS)
    print("FACT  town drains", [p for p in TOWN_CENTER_PRODUCTS])
    print("FACT  town does not drain FERTILIZER")
    print("FACT  hire6/8", cumulative_hire_cost(6), cumulative_hire_cost(8))
    print("FACT  liquidate_before_end default", cfg.liquidate_before_end)
    print("FACT  _sell_orders skips wheat feed_target while liquidating")

    recs = load(E50)
    rows = seats(recs, "H4")
    p1 = seats(recs, "P1S")
    print(f"\n======== E50 H4 n={len(rows)} vs P1-S n={len(p1)} ========")
    money = [r["money"][s] for r, s, _ in rows]
    opp = [r["money"][1 - s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    print(f"  {wins}-{len(rows) - wins}-0  mean={fmean(money):,.0f} "
          f"opp={fmean(opp):,.0f} p10={sorted(money)[max(0, int(0.1 * len(money)) - 1)]:,.0f}")
    tot = show_rev(rows)
    print("  drought/decay/esc/overflow",
          round(fmean(p.get("drought_deaths", 0) for _, _, p in rows), 2),
          round(fmean(p.get("decay_deaths", 0) for _, _, p in rows), 2),
          round(fmean(p.get("animals_escaped", 0) for _, _, p in rows), 2),
          round(fmean(p.get("shed_overflow", 0) for _, _, p in rows), 2))
    print("  fert_col", round(fmean(p.get("fertilizer_collected", 0) for _, _, p in rows), 1),
          "end_ani", round(fmean(p.get("animal_count", 0) for _, _, p in rows), 2),
          "hires", round(fmean(p.get("hires", 0) for _, _, p in rows), 1))
    ut = fmean(p.get("unit_turns", 0) for _, _, p in rows)
    print("  unit-turns", round(ut),
          "cats", {k: round(fmean(p.get("categories", {}).get(k, 0) for _, _, p in rows), 1)
                   for k in CATS})
    idle = fmean(p.get("categories", {}).get("idle", 0) for _, _, p in rows)
    print(f"  idle share {idle / ut:.4f}" if ut else "  idle share n/a")

    print("  cash d0-29", series(rows, "money_by_day"))
    print("  animals_by_day", series(rows, "animals_by_day"))
    used = []
    for d in range(30):
        vals = []
        for _, _, p in rows:
            xs = p.get("shed_by_day") or []
            if d < len(xs) and isinstance(xs[d], dict):
                vals.append(sum(xs[d].values()))
        used.append(round(fmean(vals), 1) if vals else 0)
    print("  shed_used_by_day", used)
    print("  shed WHEAT d25-29", [round(x, 1) for x in shed_item(rows, "WHEAT")[25:]])
    print("  shed WOOL  d25-29", [round(x, 1) for x in shed_item(rows, "WOOL")[25:]])
    print("  shed MILK  d25-29", [round(x, 1) for x in shed_item(rows, "MILK")[25:]])
    print("  shed FERT  d25-29", [round(x, 1) for x in shed_item(rows, "FERTILIZER")[25:]])

    print("\n  H4 losses vs P1-S:")
    for r, s, p in rows:
        if r["winner"] == 1 - s:
            print(f"    seed {r['seed']} seat {s} H4={r['money'][s]:.0f} "
                  f"P1S={r['money'][1 - s]:.0f} "
                  f"margin={r['money'][s] - r['money'][1 - s]:.0f}")

    esc = []
    for _, _, p in rows:
        esc.extend(p.get("escape_events") or [])
    print(f"\n  escape_events n={len(esc)} per-seat={len(esc) / len(rows):.2f}")
    print("  loss_days", Counter(ev.get("loss_day") for ev in esc))
    print("  animals", Counter(ev.get("animal") for ev in esc))
    print("  xy", Counter((ev.get("x"), ev.get("y")) for ev in esc).most_common(4))
    print("  held mean", round(fmean(ev.get("held") for ev in esc), 2),
          "wheat_in_shed", round(fmean(ev.get("wheat") for ev in esc), 1),
          "fed_today", dict(Counter(ev.get("fed_today") for ev in esc)))

    if os.path.exists(E53):
        dump_e53(seats(load(E53), "H4"))

    if os.path.exists(E49):
        h3 = seats(load(E49), "H3")
        h4 = seats(load(E49), "H4")
        if h3 and h4:
            print("\n======== E49 H4 vs H3 ========")
            for name, rs in (("H4", h4), ("H3", h3)):
                print(f"  {name} esc={fmean(p.get('animals_escaped', 0) for _, _, p in rs):.2f}"
                      f" wool_h={fmean(p.get('harvested', {}).get('WOOL', 0) for _, _, p in rs):.1f}"
                      f" mean={fmean(r['money'][s] for r, s, _ in rs):,.0f}"
                      f" wins={sum(1 for r, s, _ in rs if r['winner'] == s)}")

    if os.path.exists(E65):
        print("\n======== E65 extra hands ========")
        for name in ("H5", "H4"):
            rs = seats(load(E65), name)
            print(f"  {name} esc={fmean(p.get('animals_escaped', 0) for _, _, p in rs):.2f}"
                  f" drought={fmean(p.get('drought_deaths', 0) for _, _, p in rs):.2f}"
                  f" idle={fmean(p.get('categories', {}).get('idle', 0) for _, _, p in rs):.0f}"
                  f" wheat_h={fmean(p.get('harvested', {}).get('WHEAT', 0) for _, _, p in rs):.0f}")

    if os.path.exists(E63):
        print("\n======== E63 extra carrot land ========")
        for name in ("C1", "H4"):
            rs = seats(load(E63), name)
            if not rs:
                continue
            print(f"  {name} mean={fmean(r['money'][s] for r, s, _ in rs):,.0f}"
                  f" wheat_h={fmean(p.get('harvested', {}).get('WHEAT', 0) for _, _, p in rs):.0f}"
                  f" carrot_h={fmean(p.get('harvested', {}).get('CARROT', 0) for _, _, p in rs):.1f}"
                  f" esc={fmean(p.get('animals_escaped', 0) for _, _, p in rs):.2f}"
                  f" end_ani={fmean(p.get('animal_count', 0) for _, _, p in rs):.2f}")

    print(f"\nFACT  quote-rev {tot:,.0f} is not profit; wheat line includes restock churn.")
    print("""
UNUSED vs CLOSED
  CLOSED: sale_qty; sell_defer force/shed; hold_full; livestock scale;
          livestock_reserve 280/0; feed_pickup_cap all-season; feed_count_carried;
          feed_buffer 4/6; fertilize_crops; extra-land carrot; extra all-season
          hands; wheat chase / pickup-and-return; movement retune; RL/planner.
  OPEN knobs never H4-screened: hire_hour, hire_reserve, care, collect_fertilizer,
          max_crop_tiles, sell_floor_fraction, liquidate_before_end,
          land_reserve, seed_reserve, seed_batch, livestock_absorb_slack,
          livestock_cap_floor, harvest_defer_floor_fraction, drop_threshold
          (H4 uses move_ev), min_trip_value_per_step.
  Highest-EV OPEN interaction: liquidate_before_end dumps feed_buffer wheat
          on day 27-28 even though sell_defer already governs poor-quote dumps.
""")


if __name__ == "__main__":
    main()
