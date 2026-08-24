"""E53 - leftover H4 late-escape visits. No strategy change.

H4 vs P1-S, 8 seeds both seats. For each remaining day-28 loss, record
on-tile visits, pickup-and-return cost, and A/B/C for a wheat fetch.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.agent import remaining_yield_events  # noqa: E402
from kagg.econ.tables import ANIMALS, MARKET_PARAMS  # noqa: E402

SEEDS = range(8)
LAST_DAY = 29
WHEAT_BASE = MARKET_PARAMS["WHEAT"]["base"]
H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)


def remain_val(animal, placed_day, loss_day, quote):
    if placed_day is None or placed_day < 0:
        return None, None
    n = remaining_yield_events(animal, placed_day, loss_day + 1, LAST_DAY)
    if quote is None:
        quote = MARKET_PARAMS[ANIMALS[animal]["product"]]["base"]
    return n, n * quote


def late(ev):
    return ev.get("loss_day", -1) >= 27 or ev.get("obs_day", -1) >= 28


def classify_escape(ev, visits):
    """A/B/C for a pickup-and-return from an on-tile visit. Conservative on C."""
    n, val = remain_val(ev.get("animal"), ev.get("placed_day"),
                        ev.get("loss_day", LAST_DAY),
                        ev.get("quote") or (
                            ev.get("wool_quote") if ev.get("animal") == "SHEEP"
                            else ev.get("milk_quote")))
    ev["remain_n"] = n
    ev["remain_val"] = val
    tile_visits = [v for v in visits
                   if v.get("x") == ev.get("x") and v.get("y") == ev.get("y")
                   and v.get("day") == ev.get("loss_day")]
    ev["n_visits"] = len(tile_visits)
    ev["first_visit"] = tile_visits[0] if tile_visits else None
    feasible = []
    for v in tile_visits:
        wheat_ok = (v.get("wheat_hand") or 0) >= 1 or (v.get("wheat_shed") or 0) >= 1
        in_time = (v.get("pickup_cost") or 99) <= (v.get("hours_left") or 0)
        v["feasible"] = bool(wheat_ok and in_time)
        if v["feasible"]:
            feasible.append(v)
    ev["feasible_visits"] = len(feasible)
    if not tile_visits:
        return "A"
    if not feasible:
        return "A"
    if val is None:
        return "A"
    if val <= WHEAT_BASE:
        return "B"
    return "C"


def dump(records, label):
    classes, kinds, ops = Counter(), Counter(), Counter()
    printed = 0
    print(f"\n=== {label} leftover escapes ===")
    for rec in records:
        for seat in (0, 1):
            p = rec["players"][seat]
            if p["name"] != label:
                continue
            visits = p.get("at_risk_visits") or []
            for ev in p.get("escape_events") or []:
                if not late(ev):
                    continue
                cls = classify_escape(ev, visits)
                classes[cls] += 1
                kinds[ev.get("animal")] += 1
                fv = ev["first_visit"]
                if fv:
                    ops[fv.get("op")] += 1
                if printed < 20:
                    q = ev.get("wool_quote") if ev.get("animal") == "SHEEP" else ev.get("milk_quote")
                    print(f"  seed {rec['seed']} seat {seat} {ev.get('animal')} "
                          f"@({ev.get('x')},{ev.get('y')}) loss_day={ev.get('loss_day')} "
                          f"held={ev.get('held')} remain={ev.get('remain_n')}/{ev.get('remain_val')} "
                          f"q={q} visits={ev['n_visits']} feasible={ev['feasible_visits']} "
                          f"class={cls}")
                    if fv:
                        print(f"    first h{fv.get('hour')} unit={fv.get('unit')} "
                              f"wheat_hand={fv.get('wheat_hand')} wheat_shed={fv.get('wheat_shed')} "
                              f"dist_shed={fv.get('dist_shed')} cost={fv.get('pickup_cost')} "
                              f"hours_left={fv.get('hours_left')} op={fv.get('op')}/"
                              f"{fv.get('reason')} carried={fv.get('carried')}")
                    printed += 1
    print(f"  class {dict(classes)}  kinds {dict(kinds)}  first_op {dict(ops)}")
    return classes


def main():
    print("E53 leftover sheep rescue diagnostics\n")
    jobs = H.build_jobs(H.spec("H4", **H4), H.spec("P1S", **dict(B.P1_S)),
                        SEEDS, both_orders=True)
    print(f"H4 vs P1-S, {len(SEEDS)} seeds x 2 = {len(jobs)}\n", flush=True)
    records = H.run_jobs(jobs)
    base = H.save(records, "e53-h4-p1s")
    h4 = dump(records, "H4")
    dump(records, "P1S")
    print(f"\nwheat base={WHEAT_BASE}")
    print(f"H4 leftover cases: {dict(h4)}")
    n = sum(h4.values()) or 1
    maj, maj_n = h4.most_common(1)[0]
    print(f"H4 majority class={maj} ({maj_n}/{n})")
    print(f"  A={h4['A']} impossible in time or no wheat at the on-tile visit")
    print(f"  B={h4['B']} reachable but remaining value <= wheat base")
    print(f"  C={h4['C']} reachable, remaining value > wheat base")
    if maj == "C":
        print("E53 DECISION: CASE C — pickup-and-return is possible and class-C.")
    elif maj == "B":
        print("E53 DECISION: CASE B — pickup is possible but not worth the wheat. "
              "Do not implement E54.")
    else:
        print("E53 DECISION: CASE A — the typical leftover cannot complete "
              "pickup-and-return in time. Do not implement E54.")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
