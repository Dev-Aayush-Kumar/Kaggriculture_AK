"""E65 - screen two extra hands on frozen H4.

H5 = H4 + hands_per_day=8

Hypothesis: H4's wheat/livestock engine is labor-bounded (Phase 14), not
tile-bounded. Two extra hands on the same 19 wheat tiles and 6 pastures
cut drought, late escapes, and shed overflow without opening new crops.

Control: H4 stays hands_per_day=6. No agent.py change. No main.py change.
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

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)
H5 = dict(H4, hands_per_day=8)


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

    def rev(item):
        return fmean(p.get("sell_revenue", {}).get(item, 0) for _, _, p in rows)

    def harv(item):
        return fmean(p.get("harvested", {}).get(item, 0) for _, _, p in rows)

    def sold(item):
        return fmean(p.get("sell_requested", {}).get(item, 0) for _, _, p in rows)

    wheat_h, wheat_s, wheat_r = harv("WHEAT"), sold("WHEAT"), rev("WHEAT")
    milk_h, milk_s, milk_r = harv("MILK"), sold("MILK"), rev("MILK")
    wool_h, wool_s, wool_r = harv("WOOL"), sold("WOOL"), rev("WOOL")
    fert_r = rev("FERTILIZER")
    egg_r = rev("EGG")
    other = sum(rev(it) for it in ("CARROT", "TOMATO", "STRAWBERRY", "MELON"))
    move = fmean(p.get("category_share", {}).get("move", 0) for _, _, p in rows)
    idle = fmean(p.get("category_share", {}).get("idle", 0) for _, _, p in rows)
    idle_n = fmean(p.get("categories", {}).get("idle", 0) for _, _, p in rows)
    water_n = fmean(p.get("categories", {}).get("water", 0) for _, _, p in rows)
    feed_n = fmean(p.get("categories", {}).get("feed", 0) for _, _, p in rows)
    escaped = fmean(p.get("animals_escaped", 0) for _, _, p in rows)
    drought = fmean(p.get("drought_deaths", 0) for _, _, p in rows)
    decay = fmean(p.get("decay_deaths", 0) for _, _, p in rows)
    overflow = fmean(p.get("shed_overflow", 0) for _, _, p in rows)
    unsold = fmean(p.get("unsold_units", 0) for _, _, p in rows)
    hires = fmean(p.get("hires", 0) for _, _, p in rows)
    fert_c = fmean(p.get("fertilizer_collected", 0) for _, _, p in rows)
    six_days = []
    for _, _, p in rows:
        d = first_day_with(p.get("animals_by_day"), 6)
        six_days.append(99 if d is None else d)
    first6 = fmean(six_days)
    max_ani = fmean(max(p.get("animals_by_day") or [0]) for _, _, p in rows)
    end_ani = fmean(p.get("animal_count", 0) for _, _, p in rows)
    bad = sum(1 for r, s, _ in rows if r["statuses"][s] not in ("DONE", "OK", None)
              and r["statuses"][s] != 0)
    print(f"{title:<16}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n if n else 0:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}")
    print(f"  wheat h/sold/rev={wheat_h:.1f}/{wheat_s:.1f}/{wheat_r:,.0f}"
          f"  milk={milk_h:.1f}/{milk_s:.1f}/{milk_r:,.0f}"
          f"  wool={wool_h:.1f}/{wool_s:.1f}/{wool_r:,.0f}")
    print(f"  fert_c/rev={fert_c:.1f}/{fert_r:,.0f}  egg_r={egg_r:,.0f} other_crop_r={other:,.0f}")
    print(f"  move={move:.3f} idle={idle:.3f}/{idle_n:.0f} water={water_n:.0f} feed={feed_n:.0f}"
          f" hires={hires:.0f}")
    print(f"  max_ani={max_ani:.2f} end_ani={end_ani:.2f} first6={first6:.2f}"
          f" escaped={escaped:.2f} drought={drought:.2f} decay={decay:.2f}"
          f" overflow={overflow:.1f} unsold={unsold:.1f} bad={bad}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n if n else 0,
        "mean": statistics.fmean(money) if n else 0,
        "median": statistics.median(money) if n else 0,
        "p10": pct(money, 0.10), "p25": pct(money, 0.25), "p90": pct(money, 0.90),
        "escaped": escaped, "drought": drought, "decay": decay,
        "wheat_h": wheat_h, "wool_h": wool_h, "idle_n": idle_n,
        "end_ani": end_ani, "overflow": overflow,
    }


def screen_keep(cand, opp):
    return cand["wins"] >= cand["losses"] and cand["p10"] >= opp["p10"] * 0.97


def finals_promote(cand, h4):
    beat = cand["wins"] > cand["losses"]
    tail = cand["p10"] >= h4["p10"] and cand["p25"] >= h4["p25"]
    return beat and tail


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
    print(f"E65 extra crew {stage}")
    print(f"H5 hands_per_day={H5['hands_per_day']} (H4={H4['hands_per_day']})\n")
    if stage == "screen":
        cand, h4 = run_pair("H5", H5, "H4", H4, SCREEN_SEEDS, "e65-h5-h4")
        keep = screen_keep(cand, h4)
        print(f"\nH5 screen: vs H4 {cand['wins']}-{cand['losses']}-{cand['ties']} "
              f"P(win)={cand['rate']:.3f} p10 {cand['p10']:.0f} vs {h4['p10']:.0f} "
              f"keep={keep}")
        print("PROMOTION: UNKNOWN (screen only)" if keep else "PROMOTION: NO")
    elif stage == "finals":
        cand, h4 = run_pair("H5", H5, "H4", H4, FINAL_SEEDS, "e65-h5-h4-final")
        print(f"\nH5 finals: vs H4 {cand['wins']}-{cand['losses']}-{cand['ties']} "
              f"P(win)={cand['rate']:.3f}")
        print("PROMOTION:", "YES" if finals_promote(cand, h4) else "NO")
    else:
        raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
