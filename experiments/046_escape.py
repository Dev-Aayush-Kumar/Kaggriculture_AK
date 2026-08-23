"""E46/E47 - classify late animal escapes. No strategy change.

H3 vs P1-S and H3 vs H1, 8 seeds both seats. Escapes seen at dawn are
end-of-day losses from the previous day. Remaining yield uses the existing
production-event helper.
"""

import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.agent import remaining_yield_events  # noqa: E402
from kagg.econ.tables import ANIMALS, MARKET_PARAMS  # noqa: E402

SEEDS = range(8)
LAST_DAY = 29
H3 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True)
H1 = dict(B.P1_S, harvest_defer_enabled=True)


def remaining_value(animal, placed_day, loss_day, quote):
    """Cash from production events still ahead after `loss_day`."""
    if placed_day is None or placed_day < 0:
        return None, None
    n = remaining_yield_events(animal, placed_day, loss_day + 1, LAST_DAY)
    if quote is None:
        quote = MARKET_PARAMS[ANIMALS[animal]["product"]]["base"]
    return n, n * quote


def classify(ev):
    """A/B/C/D from the observed escape. Conservative on C."""
    wheat = ev.get("wheat")
    nearest = ev.get("nearest")
    n, val = remaining_value(ev.get("animal"), ev.get("placed_day"),
                             ev.get("loss_day", LAST_DAY),
                             ev.get("wool_quote") if ev.get("animal") == "SHEEP"
                             else ev.get("milk_quote"))
    ev["remain_n"] = n
    ev["remain_val"] = val
    fed = ev.get("fed_today")
    unfed = ev.get("consecutive_unfed")
    if fed is True:
        return "D"
    if wheat is None or n is None:
        return "D"
    # Dawn observation: last live hour was previous dusk. If they were already
    # one day unfed and not fed that dusk, one FEED that day would have saved.
    need_feed = fed is False and (unfed is None or unfed >= 1)
    if not need_feed and unfed == 0:
        return "D"
    hours_left = 24
    travel = (nearest or 0) + 4
    if wheat <= 0:
        return "A"
    if travel >= hours_left:
        return "A"
    if val is None:
        return "D"
    if val <= 25:
        return "B"
    return "C"


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def late(ev):
    return ev.get("loss_day", -1) >= 27 or ev.get("obs_day", -1) >= 28


def _same_day_feeds(p, day, x, y):
    hits, others = [], []
    for fe in p.get("feed_events") or []:
        if fe.get("day") != day:
            continue
        if fe.get("x") == x and fe.get("y") == y:
            hits.append(fe.get("hour"))
        else:
            others.append((fe.get("hour"), fe.get("animal"), fe.get("x"), fe.get("y")))
    return hits, others


def _day_harvests(p, day):
    return [(h.get("hour"), h.get("item"), h.get("qty"), h.get("quote"), h.get("full"))
            for h in p.get("harvest_events") or [] if h.get("day") == day]


def _risk_on(p, day):
    rows = p.get("at_risk_by_day") or []
    return rows[day] if 0 <= day < len(rows) else []


def dump_escapes(records, label):
    classes = Counter()
    kinds = Counter()
    n_seats = 0
    printed = 0
    print(f"\n=== {label} late escapes ===")
    for r, s, p in seats(records, label):
        n_seats += 1
        for ev in p.get("escape_events") or []:
            if not late(ev):
                continue
            cls = classify(ev)
            classes[cls] += 1
            kinds[ev.get("animal")] += 1
            quote = (ev.get("wool_quote") if ev.get("animal") == "SHEEP"
                     else ev.get("milk_quote"))
            held_val = None if quote is None or ev.get("held") is None else ev["held"] * quote
            loss_day = ev.get("loss_day")
            self_feeds, other_feeds = _same_day_feeds(p, loss_day, ev.get("x"), ev.get("y"))
            harvests = _day_harvests(p, loss_day)
            if printed < 32:
                print(f"  seed {r['seed']} seat {s} {p['name']} "
                      f"obs={ev.get('obs_day')}h{ev.get('obs_hour')} "
                      f"loss_day={loss_day} {ev.get('animal')} "
                      f"@({ev.get('x')},{ev.get('y')}) "
                      f"held={ev.get('held')} held_val={held_val} "
                      f"fed={ev.get('fed_today')} "
                      f"unfed={ev.get('consecutive_unfed')} "
                      f"cared={ev.get('cared_today')} "
                      f"wheat={ev.get('wheat')} shed={ev.get('shed_used')} "
                      f"nearest={ev.get('nearest')} units={ev.get('n_units')} "
                      f"placed={ev.get('placed_day')} remain={ev.get('remain_n')}/"
                      f"{ev.get('remain_val')} q={quote} class={cls}")
                print(f"    feeds_on_this_tile={self_feeds} "
                      f"other_feeds_that_day={other_feeds[:8]} "
                      f"harvests_that_day={harvests[:8]} "
                      f"at_risk_dawn={_risk_on(p, ev.get('obs_day'))}")
                printed += 1
    print(f"  seats={n_seats}  late class {dict(classes)}  kinds {dict(kinds)}")
    return classes


def run_pair(a_label, a_params, b_label, b_params, tag):
    jobs = H.build_jobs(H.spec(a_label, **a_params), H.spec(b_label, **b_params),
                        SEEDS, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: {a_label} vs {b_label}, {len(SEEDS)} seeds x 2 = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    dump_escapes(records, a_label)
    dump_escapes(records, b_label)
    print(f"raw records: {base}.json")
    return records


def main():
    print("E46/E47 late-escape diagnosis\n")
    run_pair("H3", H3, "P1S", dict(B.P1_S), "e46-h3-p1s")
    print()
    run_pair("H3", H3, "H1", H1, "e46-h3-h1")


if __name__ == "__main__":
    main()
