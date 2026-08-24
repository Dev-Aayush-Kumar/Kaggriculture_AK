"""E67 - screen a same-day plant cutoff against frozen H4.

D1 = H4 + plant_latest_hour=22

Hypothesis: H4's 1.98 drought deaths/episode are plants that miss WATER on
the planting day. The engine starts consecutive_unwatered at 1, so a plant
issued at hour 23 dies at dusk. Blocking that hour does not add land, hands,
or a second crop, and does not chase the leftover sheep.

Control: H4 stays plant_latest_hour=-1. No main.py change.
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
D1 = dict(H4, plant_latest_hour=22)


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


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses

    def harv(item):
        return fmean(p.get("harvested", {}).get(item, 0) for _, _, p in rows)

    wheat_h = harv("WHEAT")
    wool_h = harv("WOOL")
    plant_n = fmean(p.get("categories", {}).get("plant", 0) for _, _, p in rows)
    water_n = fmean(p.get("categories", {}).get("water", 0) for _, _, p in rows)
    idle_n = fmean(p.get("categories", {}).get("idle", 0) for _, _, p in rows)
    escaped = fmean(p.get("animals_escaped", 0) for _, _, p in rows)
    drought = fmean(p.get("drought_deaths", 0) for _, _, p in rows)
    decay = fmean(p.get("decay_deaths", 0) for _, _, p in rows)
    overflow = fmean(p.get("shed_overflow", 0) for _, _, p in rows)
    end_ani = fmean(p.get("animal_count", 0) for _, _, p in rows)
    print(f"{title:<16}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n if n else 0:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}")
    print(f"  wheat_h={wheat_h:.1f} wool_h={wool_h:.1f} plant={plant_n:.1f} "
          f"water={water_n:.0f} idle={idle_n:.0f}")
    print(f"  escaped={escaped:.2f} drought={drought:.2f} decay={decay:.2f} "
          f"overflow={overflow:.1f} end_ani={end_ani:.2f}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n if n else 0,
        "mean": statistics.fmean(money) if n else 0,
        "median": statistics.median(money) if n else 0,
        "p10": pct(money, 0.10), "p25": pct(money, 0.25), "p90": pct(money, 0.90),
        "escaped": escaped, "drought": drought, "decay": decay,
        "wheat_h": wheat_h, "wool_h": wool_h,
    }


def screen_keep(cand, opp):
    drought_cut = cand["drought"] <= opp["drought"] - 0.5
    beat = cand["wins"] >= cand["losses"]
    return beat and drought_cut


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
    print(f"E67 plant cutoff {stage}")
    print(f"D1 plant_latest_hour={D1['plant_latest_hour']} "
          f"(H4={H4.get('plant_latest_hour', -1)})\n")
    if stage == "screen":
        cand, h4 = run_pair("D1", D1, "H4", H4, SCREEN_SEEDS, "e67-d1-h4")
        keep = screen_keep(cand, h4)
        print(f"\nD1 screen: vs H4 {cand['wins']}-{cand['losses']}-{cand['ties']} "
              f"P(win)={cand['rate']:.3f} drought {cand['drought']:.2f} vs "
              f"{h4['drought']:.2f} keep={keep}")
        print("PROMOTION: UNKNOWN (screen only)" if keep else "PROMOTION: NO")
    elif stage == "finals":
        cand, h4 = run_pair("D1", D1, "H4", H4, FINAL_SEEDS, "e67-d1-h4-final")
        print(f"\nD1 finals: vs H4 {cand['wins']}-{cand['losses']}-{cand['ties']} "
              f"P(win)={cand['rate']:.3f} drought {cand['drought']:.2f}")
        print("PROMOTION: NO")
    else:
        raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
