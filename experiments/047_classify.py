"""E47 - classify the E46 late-escape traces.

Reads the saved E46 records. No strategy change.
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import remaining_yield_events  # noqa: E402
from kagg.econ.tables import ANIMALS, MARKET_PARAMS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")
LAST_DAY = 29
WHEAT_BASE = MARKET_PARAMS["WHEAT"]["base"]


def remaining_value(animal, placed_day, loss_day, quote):
    if placed_day is None or placed_day < 0:
        return None, None
    n = remaining_yield_events(animal, placed_day, loss_day + 1, LAST_DAY)
    if quote is None:
        quote = MARKET_PARAMS[ANIMALS[animal]["product"]]["base"]
    return n, n * quote


def classify(ev):
    """A/B/C/D from the observed escape. Conservative on C.

    A: no wheat, or travel >= a full day.
    B: reachable with wheat, but remaining production <= wheat base.
    C: wheat on hand, reachable, remaining production > wheat base.
    D: missing state or the animal does not look one-feed-from-escape.
    """
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
    if val <= WHEAT_BASE:
        return "B"
    return "C"


def late(ev):
    return ev.get("loss_day", -1) >= 27 or ev.get("obs_day", -1) >= 28


def latest(prefix):
    files = [f for f in os.listdir(RESULTS)
             if f.startswith(prefix) and f.endswith(".json")]
    if not files:
        raise FileNotFoundError(prefix)
    files.sort()
    return os.path.join(RESULTS, files[-1])


def tally(path, label):
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    classes, kinds, tiles, days = Counter(), Counter(), Counter(), Counter()
    remain_c = []
    n_seats = 0
    for rec in records:
        for seat in (0, 1):
            p = rec["players"][seat]
            if p["name"] != label:
                continue
            n_seats += 1
            for ev in p.get("escape_events") or []:
                if not late(ev):
                    continue
                cls = classify(ev)
                classes[cls] += 1
                kinds[ev.get("animal")] += 1
                tiles[(ev.get("animal"), ev.get("x"), ev.get("y"))] += 1
                days[ev.get("loss_day")] += 1
                if cls == "C" and ev.get("remain_val") is not None:
                    remain_c.append(ev["remain_val"])
    return {
        "path": path, "seats": n_seats, "classes": classes, "kinds": kinds,
        "tiles": tiles, "days": days, "remain_c": remain_c,
    }


def show(title, t):
    print(f"\n{title}")
    print(f"  file {t['path']}")
    print(f"  seats={t['seats']}  class {dict(t['classes'])}  "
          f"kinds {dict(t['kinds'])}  loss_days {dict(t['days'])}")
    print(f"  tiles {dict(t['tiles'])}")
    if t["remain_c"]:
        print(f"  class-C remaining value  n={len(t['remain_c'])}  "
              f"min={min(t['remain_c']):.0f}  max={max(t['remain_c']):.0f}  "
              f"mean={sum(t['remain_c']) / len(t['remain_c']):.0f}")


def main():
    print("E47 survival economics classification")
    print(f"wheat base (feed cost proxy) = {WHEAT_BASE}")
    p1s = latest("e46-h3-p1s")
    h1 = latest("e46-h3-h1")
    show("H3 vs P1-S / H3", tally(p1s, "H3"))
    show("H3 vs P1-S / P1S", tally(p1s, "P1S"))
    show("H3 vs H1 / H3", tally(h1, "H3"))
    show("H3 vs H1 / H1", tally(h1, "H1"))


if __name__ == "__main__":
    main()
