"""E68 - Phase 17 forensic read of E50 H4 losses. No strategy change.

Prints the seven E50 H4 vs P1-S losses: day-by-day cash/shed/harvest
divergence, wool-defer interaction, and whether the loss is volume vs
timing vs noise. Live drought tracing is experiments/069_drought.py.
"""

import json
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import harness as H  # noqa: E402
from kagg.econ.tables import MARKET_PARAMS  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
E50 = os.path.join(ROOT, "results", "e50-h4-p1s-20260824-041910.json")
WOOL_BASE = MARKET_PARAMS["WOOL"]["base"]
WOOL_POOR = WOOL_BASE * 0.30
MILK_BASE = MARKET_PARAMS["MILK"]["base"]
LAST = 29


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def pad(xs, n=30, fill=0):
    xs = list(xs or [])
    return xs + [fill] * max(0, n - len(xs))


def shed_series(p, item, n=30):
    out = []
    for d in range(n):
        xs = p.get("shed_by_day") or []
        if d < len(xs) and isinstance(xs[d], dict):
            out.append(xs[d].get(item, 0))
        else:
            out.append(0)
    return out


def tile_series(p, key, n=30):
    out = []
    for d in range(n):
        xs = p.get("tile_held_by_day") or []
        if d < len(xs) and isinstance(xs[d], dict):
            out.append(xs[d].get(key, 0))
        else:
            out.append(0)
    return out


def first_gap_day(a, b, thresh=1.0):
    """First day a stays below b by thresh and does not recover the same day."""
    for d, (x, y) in enumerate(zip(a, b)):
        if y - x >= thresh:
            return d
    return None


def persistent_gap_day(a, b, thresh=50.0):
    """First day the cash gap is >= thresh and stays non-positive after."""
    for d in range(min(len(a), len(b))):
        if b[d] - a[d] >= thresh:
            rest = [a[i] - b[i] for i in range(d, min(len(a), len(b)))]
            if all(g <= 0 for g in rest):
                return d
    return None


def poor_days(p):
    return sum(1 for q in (p.get("price_by_day") or [])
               if (q.get("WOOL") or 999) < WOOL_POOR)


def wool_rescue(p):
    n = 0
    for ev in p.get("harvest_events") or []:
        if ev.get("item") == "WOOL" and H.harvest_is_rescue(ev):
            n += ev.get("qty") or 0
    return n


def classify_loss(h, p, cash_h, cash_p, first_cash, persist):
    """A-J from the Phase 17 list. Conservative."""
    tags = []
    dh = (h.get("harvested") or {})
    dp = (p.get("harvested") or {})
    rh = h.get("sell_revenue") or {}
    rp = p.get("sell_revenue") or {}
    wheat_h = dh.get("WHEAT", 0) - dp.get("WHEAT", 0)
    milk_h = dh.get("MILK", 0) - dp.get("MILK", 0)
    wool_h = dh.get("WOOL", 0) - dp.get("WOOL", 0)
    wheat_r = rh.get("WHEAT", 0) - rp.get("WHEAT", 0)
    milk_r = rh.get("MILK", 0) - rp.get("MILK", 0)
    wool_r = rh.get("WOOL", 0) - rp.get("WOOL", 0)
    if abs(wheat_h) >= 20 or abs(wheat_r) >= 400:
        tags.append("A-wheat-volume" if wheat_h < -10 else "H-wheat-rev")
    if abs(milk_h) >= 4 or abs(milk_r) >= 400:
        tags.append("A-milk" if milk_h < 0 else "B-milk-timing")
    if abs(wool_h) >= 4 or abs(wool_r) >= 400:
        tags.append("A-wool-volume" if wool_h < 0 else "B-wool-timing")
    if (h.get("drought_deaths", 0) - p.get("drought_deaths", 0)) >= 1:
        tags.append("F-crop")
    if (h.get("animals_escaped", 0) - p.get("animals_escaped", 0)) >= 1:
        tags.append("E-livestock")
    poor = poor_days(h)
    if poor >= 10:
        tags.append("H-poor-wool-market")
    if persist is not None and persist <= 8:
        tags.append("C-early-cash")
    if not tags:
        tags.append("J-noise")
    return tags, {
        "d_wheat_h": wheat_h, "d_milk_h": milk_h, "d_wool_h": wool_h,
        "d_wheat_r": wheat_r, "d_milk_r": milk_r, "d_wool_r": wool_r,
    }


def dump_loss(r, h_seat, h, p):
    cash_h = pad(h.get("money_by_day"))
    cash_p = pad(p.get("money_by_day"))
    gap = [cash_h[d] - cash_p[d] for d in range(30)]
    first = first_gap_day(cash_h, cash_p, 20)
    persist = persistent_gap_day(cash_h, cash_p, 50)
    min_d = min(range(30), key=lambda d: gap[d])
    tags, dlt = classify_loss(h, p, cash_h, cash_p, first, persist)
    print(f"\n=== seed {r['seed']} H4 seat {h_seat}  "
          f"H4={r['money'][h_seat]:.0f} P1S={r['money'][1 - h_seat]:.0f}  "
          f"margin={r['money'][h_seat] - r['money'][1 - h_seat]:.0f} ===")
    print(f"  first cash gap>=$20 day={first}  persistent>=$50 day={persist}  "
          f"worst gap day={min_d} ${gap[min_d]:.0f}")
    print(f"  tags {tags}")
    print(f"  harvest dH4-P1S wheat={dlt['d_wheat_h']:+.0f} milk={dlt['d_milk_h']:+.1f} "
          f"wool={dlt['d_wool_h']:+.1f}")
    print(f"  quote-rev dH4-P1S wheat={dlt['d_wheat_r']:+.0f} milk={dlt['d_milk_r']:+.0f} "
          f"wool={dlt['d_wool_r']:+.0f}")
    print(f"  drought {h.get('drought_deaths')} vs {p.get('drought_deaths')}  "
          f"decay {h.get('decay_deaths')} vs {p.get('decay_deaths')}  "
          f"esc {h.get('animals_escaped')} vs {p.get('animals_escaped')}  "
          f"overflow {h.get('shed_overflow')} vs {p.get('shed_overflow')}")
    print(f"  poor-wool-days {poor_days(h)} vs {poor_days(p)}  "
          f"wool $1-floor {h.get('sell_floor_units', {}).get('WOOL', 0):.0f} vs "
          f"{p.get('sell_floor_units', {}).get('WOOL', 0):.0f}  "
          f"wool rescue-qty {wool_rescue(h):.0f} vs {wool_rescue(p):.0f}")
    print(f"  cats idle {h.get('categories', {}).get('idle', 0):.0f} vs "
          f"{p.get('categories', {}).get('idle', 0):.0f}  "
          f"water {h.get('categories', {}).get('water', 0):.0f} vs "
          f"{p.get('categories', {}).get('water', 0):.0f}  "
          f"harvest {h.get('categories', {}).get('harvest', 0):.0f} vs "
          f"{p.get('categories', {}).get('harvest', 0):.0f}  "
          f"feed {h.get('categories', {}).get('feed', 0):.0f} vs "
          f"{p.get('categories', {}).get('feed', 0):.0f}")
    print("  cash gap d0,1,3,6,8,12,16,20,24,28:",
          [round(gap[d]) for d in (0, 1, 3, 6, 8, 12, 16, 20, 24, 28)])
    wool_tile = tile_series(h, "WOOL")
    wool_p_tile = tile_series(p, "WOOL")
    print("  H4 wool-on-tile d6-29", [round(x, 1) for x in wool_tile[6:]])
    print("  P1S wool-on-tile     ", [round(x, 1) for x in wool_p_tile[6:]])
    # wool harvest events by day
    by_d = Counter()
    pby = Counter()
    for ev in h.get("harvest_events") or []:
        if ev.get("item") == "WOOL":
            by_d[ev.get("day")] += ev.get("qty") or 0
    for ev in p.get("harvest_events") or []:
        if ev.get("item") == "WOOL":
            pby[ev.get("day")] += ev.get("qty") or 0
    days = sorted(set(by_d) | set(pby))
    if days:
        print("  wool harvest by day H4/P1S:",
              [(d, round(by_d[d], 1), round(pby[d], 1)) for d in days])
    # milk same
    mby, mpby = Counter(), Counter()
    for ev in h.get("harvest_events") or []:
        if ev.get("item") == "MILK":
            mby[ev.get("day")] += ev.get("qty") or 0
    for ev in p.get("harvest_events") or []:
        if ev.get("item") == "MILK":
            mpby[ev.get("day")] += ev.get("qty") or 0
    mdays = sorted(set(mby) | set(mpby))
    if mdays:
        print("  milk harvest by day H4/P1S:",
              [(d, round(mby[d], 1), round(mpby[d], 1)) for d in mdays])
    quotes = h.get("price_by_day") or []
    poor_list = [d for d, q in enumerate(quotes) if (q.get("WOOL") or 999) < WOOL_POOR]
    print(f"  poor wool quote days ({WOOL_POOR:.0f} floor): {poor_list}")
    return {
        "seed": r["seed"], "seat": h_seat,
        "margin": r["money"][h_seat] - r["money"][1 - h_seat],
        "first": first, "persist": persist, "worst_day": min_d,
        "worst": gap[min_d], "tags": tags, **dlt,
        "poor": poor_days(h),
        "drought_h": h.get("drought_deaths"), "drought_p": p.get("drought_deaths"),
    }


def win_contrast(recs):
    wins, losses = [], []
    for r in recs:
        for s in (0, 1):
            if r["players"][s]["name"] != "H4":
                continue
            h, p = r["players"][s], r["players"][1 - s]
            row = {
                "win": r["winner"] == s,
                "margin": r["money"][s] - r["money"][1 - s],
                "wheat_h": h.get("harvested", {}).get("WHEAT", 0),
                "milk_h": h.get("harvested", {}).get("MILK", 0),
                "wool_h": h.get("harvested", {}).get("WOOL", 0),
                "wheat_r": h.get("sell_revenue", {}).get("WHEAT", 0),
                "milk_r": h.get("sell_revenue", {}).get("MILK", 0),
                "wool_r": h.get("sell_revenue", {}).get("WOOL", 0),
                "poor": poor_days(h),
                "wool_floor": h.get("sell_floor_units", {}).get("WOOL", 0),
                "idle": h.get("categories", {}).get("idle", 0),
                "water": h.get("categories", {}).get("water", 0),
                "harvest": h.get("categories", {}).get("harvest", 0),
            }
            (wins if row["win"] else losses).append(row)
    print("\n======== E50 H4 wins vs losses (own stats) ========")
    for label, group in (("WINS", wins), ("LOSSES", losses)):
        print(f"{label} n={len(group)}")
        for k in ("margin", "wheat_h", "milk_h", "wool_h", "wheat_r", "milk_r",
                  "wool_r", "poor", "wool_floor", "idle", "water", "harvest"):
            print(f"  {k:12} {fmean(x[k] for x in group):10.1f}")


def main():
    recs = load(E50)
    print("E68 Phase 17 E50 loss forensics (read-only)\n")
    losses = []
    for r in recs:
        for s in (0, 1):
            if r["players"][s]["name"] != "H4":
                continue
            if r["winner"] == s:
                continue
            losses.append(dump_loss(r, s, r["players"][s], r["players"][1 - s]))
    print("\n======== loss table ========")
    print(f"{'seed':>5} {'seat':>4} {'margin':>8} {'first':>6} {'persist':>8} "
          f"{'worstD':>7} {'dWheatH':>8} {'dMilkH':>7} {'dWoolH':>7} "
          f"{'dWoolR':>8} {'poor':>5}")
    for L in losses:
        print(f"{L['seed']:5} {L['seat']:4} {L['margin']:8.0f} "
              f"{str(L['first']):>6} {str(L['persist']):>8} {L['worst_day']:7} "
              f"{L['d_wheat_h']:8.0f} {L['d_milk_h']:7.1f} {L['d_wool_h']:7.1f} "
              f"{L['d_wool_r']:8.0f} {L['poor']:5}")
        print(f"      tags {L['tags']}")
    win_contrast(recs)


if __name__ == "__main__":
    main()
