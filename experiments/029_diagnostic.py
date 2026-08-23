"""E29 - diagnose the E28 finalists against L0/P1-S.

Reads the latest e28-finals-*.json. No engine episodes.
"""

import glob
import json
import os
import statistics
import sys

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))]


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def sold_from(player, item, day):
    by_day = player.get("sell_qty_by_day", {}).get(item) or {}
    return sum(q for d, q in by_day.items() if int(d) >= day)


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
        "milk_f": fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows),
        "wool_f": fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows),
        "milk_px": (milk_r / milk_s) if milk_s else 0,
        "wool_px": (wool_r / wool_s) if wool_s else 0,
        "unsold_m": fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows),
        "unsold_w": fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows),
        "last_w": fmean(sold_from(p, "WOOL", 29) for _, _, p in rows),
        "liq_w": fmean(sold_from(p, "WOOL", 28) for _, _, p in rows),
        "lost": fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                      for _, _, p in rows),
    }


def show(path, a, b):
    recs = json.load(open(path, encoding="utf-8"))
    left, right = row(recs, a), row(recs, b)
    print(f"\n{os.path.basename(path)}  {a} vs {b}")
    print(f"  {a}: {left['w']}-{left['l']}-{left['t']} rate={left['rate']:.2f} "
          f"mean={left['mean']:,.0f} p10={left['p10']:,.0f} p25={left['p25']:,.0f}")
    print(f"  {b}: {right['w']}-{right['l']}-{right['t']} rate={right['rate']:.2f} "
          f"mean={right['mean']:,.0f} p10={right['p10']:,.0f} p25={right['p25']:,.0f}")
    print(f"  wool floor {left['wool_f']:.1f} vs {right['wool_f']:.1f}  "
          f"px {left['wool_px']:.1f} vs {right['wool_px']:.1f}")
    print(f"  last-day wool {left['last_w']:.1f} vs {right['last_w']:.1f}  "
          f"d28+ wool {left['liq_w']:.1f} vs {right['liq_w']:.1f}")
    print(f"  unsold m/w {left['unsold_m']:.1f}/{left['unsold_w']:.1f} vs "
          f"{right['unsold_m']:.1f}/{right['unsold_w']:.1f}")
    return left, right


def main():
    paths = sorted(glob.glob(os.path.join(RESULTS, "e28-finals-*.json")))
    if not paths:
        raise SystemExit("no e28-finals JSON found")
    strongest = None
    best_gap = -999
    for path in paths:
        label = os.path.basename(path).split("-")[2].split(".")[0]  # L3 or L1
        # filenames are e28-finals-L3-timestamp.json
        tag = os.path.basename(path).split("e28-finals-")[1].split("-20")[0]
        cand, l0 = show(path, tag, "L0")
        gap = cand["w"] - cand["l"]
        if gap > best_gap:
            best_gap = gap
            strongest = (tag, cand, l0)
    tag, cand, l0 = strongest
    print(f"\nstrongest on P(win) gap: {tag}")
    if cand["w"] > cand["l"] and cand["p10"] >= l0["p10"] * 0.97:
        print("E29: candidate is a credible P1-S challenger.")
    elif cand["w"] > cand["l"] and cand["p10"] < l0["p10"] * 0.97:
        print("E29: P(win) up but p10 damaged. Do not promote. Mechanism mixed.")
    else:
        print("E29: candidate does not beat L0. Retain P1-S.")


if __name__ == "__main__":
    main()
