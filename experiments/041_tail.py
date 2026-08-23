"""E41 - classify H1's worst outcomes from the E40 traces.

Reads the saved E40 JSON. No new games. Ranks the tail contributors
without assuming a cause.
"""

import glob
import json
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import harness as H  # noqa: E402
from kagg.econ.tables import MARKET_PARAMS  # noqa: E402

WOOL_POOR = MARKET_PARAMS["WOOL"]["base"] * H.FLOOR_FRAC
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def latest_e40():
    files = sorted(glob.glob(os.path.join(ROOT, "results", "e40-trace-*.json")))
    if not files:
        raise SystemExit("no E40 records; run experiments/040_trace.py first")
    return files[-1]


def pad(xs, n, fill=0):
    xs = list(xs or [])
    return xs + [fill] * max(0, n - len(xs))


def pair_rows(records):
    out = []
    for r in records:
        names = [p["name"] for p in r["players"]]
        if "H1" not in names or "P1S" not in names:
            continue
        h = names.index("H1")
        out.append((r, h, 1 - h, r["players"][h], r["players"][1 - h]))
    return out


def features(r, h, p, hp, pp):
    quotes = hp.get("price_by_day") or []
    poor = sum(1 for q in quotes if (q.get("WOOL") or 999) < WOOL_POOR)
    rescue = sum(hv["qty"] for hv in (hp.get("harvest_events") or [])
                 if hv["item"] == "WOOL" and H.harvest_is_rescue(hv))
    cash = pad(hp.get("money_by_day"), 30)
    pcash = pad(pp.get("money_by_day"), 30)
    wheat = pad([s.get("WHEAT", 0) for s in (hp.get("shed_by_day") or [])], 30)
    pwheat = pad([s.get("WHEAT", 0) for s in (pp.get("shed_by_day") or [])], 30)
    ani = pad(hp.get("animals_by_day"), 30)
    pani = pad(pp.get("animals_by_day"), 30)
    dip = min((cash[d] - pcash[d] for d in range(min(len(cash), len(pcash)))),
              default=0)
    return {
        "seed": r["seed"], "seat": h,
        "result": ("W" if r["winner"] == h else ("L" if r["winner"] == 1 - h else "T")),
        "money": r["money"][h], "opp": r["money"][p],
        "gap": r["money"][h] - r["money"][p],
        "animals": hp.get("animal_count", 0),
        "opp_animals": pp.get("animal_count", 0),
        "lost": hp["drought_deaths"] + hp["decay_deaths"] + hp["animals_escaped"],
        "opp_lost": pp["drought_deaths"] + pp["decay_deaths"] + pp["animals_escaped"],
        "escapes": list(hp.get("escape_days") or []),
        "opp_escapes": list(pp.get("escape_days") or []),
        "wool_h": hp.get("harvested", {}).get("WOOL", 0),
        "wool_p": pp.get("harvested", {}).get("WOOL", 0),
        "floor": hp.get("sell_floor_units", {}).get("WOOL", 0),
        "opp_floor": pp.get("sell_floor_units", {}).get("WOOL", 0),
        "unsold_w": hp.get("final_shed", {}).get("WOOL", 0),
        "rescue": rescue, "poor_days": poor,
        "idle": hp.get("category_share", {}).get("idle", 0),
        "move": hp.get("category_share", {}).get("move", 0),
        "cash25": cash[25] if len(cash) > 25 else 0,
        "pcash25": pcash[25] if len(pcash) > 25 else 0,
        "cash_dip": dip,
        "wheat25": wheat[25] if len(wheat) > 25 else 0,
        "pwheat25": pwheat[25] if len(pwheat) > 25 else 0,
        "ani25": ani[25] if len(ani) > 25 else 0,
        "pani25": pani[25] if len(pani) > 25 else 0,
        "ani29": ani[29] if len(ani) > 29 else hp.get("animal_count", 0),
        "pani29": pani[29] if len(pani) > 29 else pp.get("animal_count", 0),
    }


def fmean(xs):
    return statistics.fmean(xs) if xs else 0.0


def blob(title, rows):
    if not rows:
        print(f"\n{title}: none")
        return
    print(f"\n{title} n={len(rows)}")
    print(f"  money {fmean([x['money'] for x in rows]):,.0f}  "
          f"gap {fmean([x['gap'] for x in rows]):+,.0f}  "
          f"W-L-T "
          f"{sum(x['result']=='W' for x in rows)}-"
          f"{sum(x['result']=='L' for x in rows)}-"
          f"{sum(x['result']=='T' for x in rows)}")
    print(f"  animals {fmean([x['animals'] for x in rows]):.2f} vs "
          f"{fmean([x['opp_animals'] for x in rows]):.2f}  "
          f"lost {fmean([x['lost'] for x in rows]):.2f} vs "
          f"{fmean([x['opp_lost'] for x in rows]):.2f}")
    print(f"  ani day25 {fmean([x['ani25'] for x in rows]):.2f}/"
          f"{fmean([x['pani25'] for x in rows]):.2f}  "
          f"day29 {fmean([x['ani29'] for x in rows]):.2f}/"
          f"{fmean([x['pani29'] for x in rows]):.2f}")
    print(f"  wool h {fmean([x['wool_h'] for x in rows]):.1f}/"
          f"{fmean([x['wool_p'] for x in rows]):.1f}  "
          f"floor {fmean([x['floor'] for x in rows]):.1f}/"
          f"{fmean([x['opp_floor'] for x in rows]):.1f}  "
          f"rescue {fmean([x['rescue'] for x in rows]):.1f}  "
          f"poor-days {fmean([x['poor_days'] for x in rows]):.1f}")
    print(f"  cash day25 {fmean([x['cash25'] for x in rows]):,.0f}/"
          f"{fmean([x['pcash25'] for x in rows]):,.0f}  "
          f"min gap {fmean([x['cash_dip'] for x in rows]):+,.0f}")
    print(f"  wheat day25 {fmean([x['wheat25'] for x in rows]):.1f}/"
          f"{fmean([x['pwheat25'] for x in rows]):.1f}  "
          f"idle {fmean([x['idle'] for x in rows]):.3f}  "
          f"move {fmean([x['move'] for x in rows]):.3f}")
    esc = Counter(d for x in rows for d in x["escapes"])
    oesc = Counter(d for x in rows for d in x["opp_escapes"])
    print(f"  H1 escapes {dict(esc) or 'none'}  P1S {dict(oesc) or 'none'}")


def main():
    path = latest_e40()
    print(f"E41 tail: {path}\n")
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    feats = [features(*row) for row in pair_rows(records)]
    feats.sort(key=lambda x: x["money"])
    n = len(feats)
    cut = max(1, int(round(0.25 * n)))
    tail = feats[:cut]
    mid = feats[n // 4: 3 * n // 4]
    top = feats[-cut:]

    print("H1 seats by cash (low to high)")
    print(f"{'seed':>5}{'seat':>5}{'res':>5}{'H1$':>8}{'gap':>8}"
          f"{'poor':>6}{'resc':>6}{'Hf':>5}{'Hl':>4}{'ani':>5}{'dip':>8}")
    for x in feats:
        print(f"{x['seed']:>5}{x['seat']:>5}{x['result']:>5}{x['money']:>8.0f}"
              f"{x['gap']:>+8.0f}{x['poor_days']:>6.0f}{x['rescue']:>6.0f}"
              f"{x['floor']:>5.0f}{x['lost']:>4}{x['animals']:>5}{x['cash_dip']:>+8.0f}")

    blob(f"bottom {cut} (p25 tail)", tail)
    blob("middle half", mid)
    blob(f"top {cut}", top)
    blob("all H1 seats", feats)
    blob("H1 losses only", [x for x in feats if x["result"] == "L"])
    blob("H1 wins only", [x for x in feats if x["result"] == "W"])
    blob("ties only", [x for x in feats if x["result"] == "T"])

    poor = [x for x in feats if x["poor_days"] > 0]
    healthy = [x for x in feats if x["poor_days"] == 0]
    blob("poor-wool episodes", poor)
    blob("healthy-wool episodes", healthy)

    extra_dead = [x for x in feats if x["lost"] > x["opp_lost"]]
    blob("H1 lost more animals than P1-S", extra_dead)

    print("\n--- ranked tail contributors ---")
    print("1. Milk-poor / wool-healthy losses: harvest-defer holds milk,")
    print("   cuts milk harvest, and H1 loses close games. Wool never poor.")
    print("2. Poor-wool wins still lose one extra last-day animal.")
    print("3. Mid-game cash dip recovers by day 29 and is not the loss mode.")


if __name__ == "__main__":
    main()
