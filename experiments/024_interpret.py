"""E24/E25 - classify the E23 three-way and print economic diagnostics.

Reads the latest results/e23-controls-*.json. No engine episodes.
"""

import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(vals, q):
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def row(records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    milk_s = fmean(p.get("sell_requested", {}).get("MILK", 0) for _, _, p in rows)
    wool_s = fmean(p.get("sell_requested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    return {
        "n": n, "w": wins, "l": losses, "t": ties, "rate": wins / n if n else 0,
        "mean": statistics.fmean(money), "median": statistics.median(money),
        "p10": pct(money, 0.10), "p25": pct(money, 0.25),
        "milk_h": fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows),
        "wool_h": fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows),
        "milk_s": milk_s, "wool_s": wool_s, "milk_r": milk_r, "wool_r": wool_r,
        "milk_px": (milk_r / milk_s) if milk_s else 0,
        "wool_px": (wool_r / wool_s) if wool_s else 0,
        "milk_f": fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows),
        "wool_f": fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows),
        "unsold_m": fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows),
        "unsold_w": fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows),
        "animals": fmean(p.get("animal_count", 0) for _, _, p in rows),
        "sale_day_m": _mean_sale_day(rows, "MILK"),
        "sale_day_w": _mean_sale_day(rows, "WOOL"),
    }


def _mean_sale_day(rows, item):
    days = []
    for _, _, p in rows:
        by_day = p.get("sell_qty_by_day", {}).get(item) or {}
        total = sum(by_day.values())
        if total:
            days.append(sum(int(d) * q for d, q in by_day.items()) / total)
    return fmean(days)


def beats(a, b):
    """Directional: more wins than losses, p10 not materially worse."""
    return a["w"] > a["l"] and a["p10"] >= b["p10"] * 0.97


def close(a, b):
    """Approximately equal: |win gap| <= 4 and p10 within 3%."""
    return abs(a["w"] - a["l"]) <= 4 and abs(a["p10"] - b["p10"]) <= max(1, 0.03 * b["p10"])


def show(title, a, b, la, lb):
    print(f"\n{title}")
    print(f"  {la}: {a['w']}-{a['l']}-{a['t']} rate={a['rate']:.2f} "
          f"mean={a['mean']:,.0f} med={a['median']:,.0f} "
          f"p10={a['p10']:,.0f} p25={a['p25']:,.0f}")
    print(f"  {lb}: {b['w']}-{b['l']}-{b['t']} rate={b['rate']:.2f} "
          f"mean={b['mean']:,.0f} med={b['median']:,.0f} "
          f"p10={b['p10']:,.0f} p25={b['p25']:,.0f}")
    print(f"  milk floor {a['milk_f']:.1f} vs {b['milk_f']:.1f}  "
          f"wool floor {a['wool_f']:.1f} vs {b['wool_f']:.1f}")
    print(f"  milk px {a['milk_px']:.1f} vs {b['milk_px']:.1f}  "
          f"wool px {a['wool_px']:.1f} vs {b['wool_px']:.1f}")
    print(f"  sale day m/w {a['sale_day_m']:.1f}/{a['sale_day_w']:.1f} vs "
          f"{b['sale_day_m']:.1f}/{b['sale_day_w']:.1f}")
    print(f"  unsold m/w {a['unsold_m']:.1f}/{a['unsold_w']:.1f} vs "
          f"{b['unsold_m']:.1f}/{b['unsold_w']:.1f}  "
          f"animals {a['animals']:.2f} vs {b['animals']:.2f}")


def classify(p1s_v_p1, p1_v_p1s, qd_v_p1s, p1s_v_qd, qd_v_p1, p1_v_qd):
    p1s_beats_p1 = beats(p1s_v_p1, p1_v_p1s)
    qd_beats_p1s = beats(qd_v_p1s, p1s_v_qd)
    qd_eq_p1s = close(qd_v_p1s, p1s_v_qd)
    qd_beats_p1 = beats(qd_v_p1, p1_v_qd)
    p1s_beats_p1_clear = p1s_beats_p1
    if p1s_beats_p1_clear and qd_eq_p1s:
        return 1, "P1-S", "Sell deferral is the meaningful improvement; sale qty is not needed."
    if p1s_beats_p1_clear and qd_beats_p1s:
        return 2, "QD", "Sale quantity adds value beyond sell deferral."
    if (not p1s_beats_p1_clear) and qd_beats_p1 and qd_beats_p1s:
        return 3, "QD", "Possible interaction; mark as HYPOTHESIS."
    if (not p1s_beats_p1_clear) and (not qd_beats_p1):
        return 4, "P1", "Neither control clearly beats P1."
    return 5, "UNKNOWN", "Differences are small or inconsistent."


def main():
    paths = sorted(glob.glob(os.path.join(RESULTS, "e23-controls-*.json")))
    if not paths:
        raise SystemExit("no e23-controls JSON found")
    path = paths[-1]
    records = json.load(open(path, encoding="utf-8"))
    print(f"E24/E25 reading {path}")

    pair = {}
    for a, b in (("P1S", "P1"), ("QD", "P1S"), ("QD", "P1")):
        recs = [r for r in records if set(r["agents"]) == {a, b}]
        pair[(a, b)] = row(recs, a)
        pair[(b, a)] = row(recs, b)

    show("P1-S vs P1", pair[("P1S", "P1")], pair[("P1", "P1S")], "P1S", "P1")
    show("QD vs P1-S", pair[("QD", "P1S")], pair[("P1S", "QD")], "QD", "P1S")
    show("QD vs P1", pair[("QD", "P1")], pair[("P1", "QD")], "QD", "P1")

    case, incumbent, note = classify(
        pair[("P1S", "P1")], pair[("P1", "P1S")],
        pair[("QD", "P1S")], pair[("P1S", "QD")],
        pair[("QD", "P1")], pair[("P1", "QD")])
    print(f"\nCASE {case}: incumbent={incumbent}")
    print(note)


if __name__ == "__main__":
    main()
