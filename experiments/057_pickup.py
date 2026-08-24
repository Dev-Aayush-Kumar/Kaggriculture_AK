"""E57 - screen a one-wheat feed pickup cap against frozen H4.

H4 and P1-S stay frozen (feed_pickup_cap=0). PICK1 only changes that cap.

Hypothesis: n_animals wheat per FEED trip empties the shed into inventories,
triggers BUY_PRODUCT restocks of wheat still in hand, and starves day-1 cash.
Capping pickup at 1 stops that churn and raises P(win).
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402

SCREEN_SEEDS = range(8)
FINAL_SEEDS = range(32)

P1S = dict(B.P1_S)
H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)
PICK1 = dict(H4, feed_pickup_cap=1)


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def first_day_with(series, n):
    for d, v in enumerate(series or []):
        if v >= n:
            return d
    return None


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    wheat_r = fmean(p.get("sell_revenue", {}).get("WHEAT", 0) for _, _, p in rows)
    fert_r = fmean(p.get("sell_revenue", {}).get("FERTILIZER", 0) for _, _, p in rows)
    wheat_h = fmean(p.get("harvested", {}).get("WHEAT", 0) for _, _, p in rows)
    wheat_s = fmean(p.get("sell_requested", {}).get("WHEAT", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    escaped = fmean(p.get("animals_escaped", 0) for _, _, p in rows)
    drought = fmean(p.get("drought_deaths", 0) for _, _, p in rows)
    buys = fmean(p.get("market_ops", {}).get("BUY_PRODUCT", 0) for _, _, p in rows)
    pickups = fmean(p.get("ops", {}).get("PICKUP", 0) for _, _, p in rows)
    feeds = fmean(p.get("ops", {}).get("FEED", 0) for _, _, p in rows)
    six_days = []
    for _, _, p in rows:
        d = first_day_with(p.get("animals_by_day"), 6)
        six_days.append(99 if d is None else d)
    first6 = fmean(six_days)
    day1 = fmean(p["money_by_day"][1] for _, _, p in rows
                 if len(p.get("money_by_day") or []) > 1)
    bad = sum(1 for r, s, _ in rows if r["statuses"][s] not in ("DONE", "OK", None)
              and r["statuses"][s] != 0)
    print(f"{title:<16}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n if n else 0:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}")
    print(f"  wheat h/sold/rev={wheat_h:.1f}/{wheat_s:.1f}/{wheat_r:,.0f}  "
          f"wool_r/f={wool_r:,.0f}/{wool_f:.1f}  milk_r={milk_r:,.0f}  fert_r={fert_r:,.0f}")
    print(f"  first6={first6:.2f} day1$={day1:.0f} buy_prod={buys:.1f} "
          f"pickup/feed={pickups:.1f}/{feeds:.1f} esc={escaped:.2f} "
          f"drought={drought:.2f} bad={bad}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n if n else 0,
        "mean": statistics.fmean(money) if n else 0,
        "median": statistics.median(money) if n else 0,
        "p10": pct(money, 0.10), "p25": pct(money, 0.25),
        "escaped": escaped, "drought": drought, "first6": first6,
        "day1": day1, "buys": buys, "wheat_s": wheat_s,
    }


def screen_keep(cand, opp):
    return cand["wins"] >= cand["losses"] and cand["p10"] >= opp["p10"] * 0.97


def finals_promote(cand_h4, h4, cand_p, p1s):
    beat_h4 = cand_h4["wins"] > cand_h4["losses"]
    beat_p = cand_p["wins"] > cand_p["losses"]
    tail_h4 = cand_h4["p10"] >= h4["p10"] and cand_h4["p25"] >= h4["p25"]
    tail_p = cand_p["p10"] >= p1s["p10"] and cand_p["p25"] >= p1s["p25"]
    return beat_h4 and beat_p and tail_h4 and tail_p


def run_pair(a_label, a_params, b_label, b_params, seeds, tag):
    jobs = H.build_jobs(H.spec(a_label, **a_params), H.spec(b_label, **b_params),
                        seeds, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: {a_label} vs {b_label}, {len(seeds)} seeds x 2 = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    h = (f"{'matchup':<16}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}")
    print("\n" + h)
    print("-" * len(h))
    a = summarize(f"{a_label} vs {b_label}", records, a_label)
    b = summarize(f"{b_label} vs {a_label}", records, b_label)
    print(f"raw records: {base}.json")
    return a, b


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "screen"
    print(f"E57 feed-pickup cap {stage}\n")
    if stage == "screen":
        cand_h4, h4 = run_pair("PICK1", PICK1, "H4", H4, SCREEN_SEEDS,
                               "e57-pick1-h4")
        print()
        cand_p, p1s = run_pair("PICK1", PICK1, "P1S", P1S, SCREEN_SEEDS,
                               "e57-pick1-p1s")
        print(f"\nPICK1 screen: vs H4 {cand_h4['wins']}-{cand_h4['losses']}-"
              f"{cand_h4['ties']} p10 {cand_h4['p10']:.0f} vs {h4['p10']:.0f} "
              f"day1$ {cand_h4['day1']:.0f} vs {h4['day1']:.0f} "
              f"wheat_sold {cand_h4['wheat_s']:.0f} vs {h4['wheat_s']:.0f} "
              f"buys {cand_h4['buys']:.1f} vs {h4['buys']:.1f}")
        print(f"         vs P1S {cand_p['wins']}-{cand_p['losses']}-"
              f"{cand_p['ties']} p10 {cand_p['p10']:.0f} vs {p1s['p10']:.0f}")
        vs_h4 = screen_keep(cand_h4, h4)
        vs_p = screen_keep(cand_p, p1s)
        if vs_h4 and vs_p:
            print("         KEEP")
            print("Run: python experiments/057_pickup.py finals")
        else:
            print(f"         DROP  (vs H4 keep={vs_h4} vs P1S keep={vs_p})")
        return
    if stage == "finals":
        cand_h4, h4 = run_pair("PICK1", PICK1, "H4", H4, FINAL_SEEDS,
                               "e58-pick1-h4")
        print()
        cand_p, p1s = run_pair("PICK1", PICK1, "P1S", P1S, FINAL_SEEDS,
                               "e58-pick1-p1s")
        print(f"\nPICK1 finals: vs H4 {cand_h4['wins']}-{cand_h4['losses']}-"
              f"{cand_h4['ties']} p10 {cand_h4['p10']:.0f}/{h4['p10']:.0f} "
              f"p25 {cand_h4['p25']:.0f}/{h4['p25']:.0f}")
        print(f"          vs P1S {cand_p['wins']}-{cand_p['losses']}-"
              f"{cand_p['ties']} p10 {cand_p['p10']:.0f}/{p1s['p10']:.0f} "
              f"p25 {cand_p['p25']:.0f}/{p1s['p25']:.0f}")
        if finals_promote(cand_h4, h4, cand_p, p1s):
            print("E58: PICK1 beats H4 and P1-S without tail damage.")
        else:
            print("E58: PICK1 does not replace H4.")
        return
    raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
