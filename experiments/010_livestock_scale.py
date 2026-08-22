"""E10 - livestock scale sweep around the B0 incumbent.

B0 is 3 cows + 3 sheep. The five configs keep that 1:1 mix and the rest of the
B0 Config (zone_nearest, wheat, 6 hands, no geese, no land) and only change
how many pairs are requested. The executor and purse logic are unchanged, so
the 4+4 and 5+5 rows may buy fewer animals than they ask for if day-0 cash
runs out -- that is part of the scale measurement, not a second planner.

Screen: each non-B0 scale vs B0 on 8 seeds in both seats, plus a B0 mirror
on those seeds (no seat swap). Pick at most three variants, then evaluate
finalists vs B0 and in self-play on a larger paired seed set.

B0 vs B0 at 32 seeds is E9; this file does not rerun that block.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SCREEN_SEEDS = range(8)
FINAL_SEEDS = range(32)

BASE = dict(routing="zone_nearest", geese=0, crops=("WHEAT",), hands_per_day=6)

# Derived from B0's 3+3 by stepping one pair at a time. Labels are scale, not
# a new strategy family.
SCALES = {
    "B_1_1": dict(cows=1, sheep=1),
    "B_2_2": dict(cows=2, sheep=2),
    "B0":    dict(cows=3, sheep=3),
    "B_4_4": dict(cows=4, sheep=4),
    "B_5_5": dict(cows=5, sheep=5),
}


def spec_for(label):
    params = dict(BASE)
    params.update(SCALES[label])
    return H.spec(label, **params)


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, max(0, int(q * len(sorted_vals)) - (0 if q == 0 else 1)))
    return sorted_vals[k]


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    if not n:
        print(f"{title:<22}   n=0")
        return None
    money = sorted(r["money"][s] for r, s, _ in rows)
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = sum(1 for r, s, _ in rows if r["winner"] is None)
    margins = [r["money"][s] - r["money"][1 - s] for r, s, _ in rows]
    milk_h = statistics.fmean(p["harvested"].get("MILK", 0) for _, _, p in rows)
    wool_h = statistics.fmean(p["harvested"].get("WOOL", 0) for _, _, p in rows)
    milk_r = statistics.fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = statistics.fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = statistics.fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = statistics.fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold_m = statistics.fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = statistics.fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    animals = statistics.fmean(p.get("animal_count", 0) for _, _, p in rows)
    move = statistics.fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = statistics.fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    lost = statistics.fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                            for _, _, p in rows)
    print(f"{title:<22}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}"
          f"{statistics.fmean(margins):>+9,.0f}")
    print(f"  animals={animals:.1f}  milk harv/rev/floor={milk_h:.1f}/{milk_r:,.0f}/{milk_f:.1f}"
          f"  wool={wool_h:.1f}/{wool_r:,.0f}/{wool_f:.1f}"
          f"  unsold m/w={unsold_m:.1f}/{unsold_w:.1f}"
          f"  move={move:.3f} idle={idle:.3f} lost={lost:.2f}")
    return {
        "label": label, "n": n, "wins": wins, "losses": losses, "ties": ties,
        "rate": wins / n, "mean": statistics.fmean(money),
        "p10": pct(money, 0.10), "median": statistics.median(money),
        "margin": statistics.fmean(margins),
    }


def header():
    h = (f"{'matchup':<22}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p90':>8}{'sd':>8}{'margin':>9}")
    print("\n" + h)
    print("-" * len(h))


def progress_fn(t0):
    def progress(rec, i, total):
        if i % 12 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)
    return progress


def pick_finalists(screen_rows):
    """At most two challengers plus B0. Win rate vs B0, then p10, then mean."""
    chall = [r for r in screen_rows if r and r["label"] != "B0"]
    chall.sort(key=lambda r: (r["rate"], r["p10"], r["mean"]), reverse=True)
    picked = ["B0"] + [r["label"] for r in chall[:2]]
    print("\nfinalists:", ", ".join(picked))
    return picked


def main():
    b0 = spec_for("B0")
    jobs = H.build_jobs(b0, b0, SCREEN_SEEDS, both_orders=False)
    for label in SCALES:
        if label == "B0":
            continue
        jobs += H.build_jobs(spec_for(label), b0, SCREEN_SEEDS, both_orders=True)

    t0 = time.perf_counter()
    print(f"E10 screen: {len(jobs)} episodes "
          f"(4 scales x 8 seeds x 2 seats + 8 B0 mirrors)\n", flush=True)
    screen = H.run_jobs(jobs, progress=progress_fn(t0))
    base_s = H.save(screen, "e10-screen")

    header()
    rows = []
    for label in SCALES:
        if label == "B0":
            recs = [r for r in screen if r["agents"] == ["B0", "B0"]]
        else:
            recs = [r for r in screen if set(r["agents"]) == {label, "B0"}]
        rows.append(summarize(f"{label} vs B0", recs, label))

    bad = [(r["seed"], r["agents"], r["statuses"]) for r in screen
           if any(s != "DONE" for s in r["statuses"])]
    print(f"\nscreen bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in screen for p in r['players'])}")
    print(f"screen records: {base_s}.json")

    finalists = pick_finalists(rows)
    challengers = [x for x in finalists if x != "B0"]

    jobs = []
    for label in challengers:
        jobs += H.build_jobs(spec_for(label), b0, FINAL_SEEDS, both_orders=True)
        jobs += H.build_jobs(spec_for(label), spec_for(label), FINAL_SEEDS,
                             both_orders=False)
    # Pair the two challengers if both survived, so scale-vs-scale is measured.
    if len(challengers) == 2:
        jobs += H.build_jobs(spec_for(challengers[0]), spec_for(challengers[1]),
                             FINAL_SEEDS, both_orders=True)

    t1 = time.perf_counter()
    print(f"\nE10 finals: {len(jobs)} episodes on {len(FINAL_SEEDS)} seeds\n",
          flush=True)
    finals = H.run_jobs(jobs, progress=progress_fn(t1)) if jobs else []
    base_f = H.save(finals, "e10-finals") if finals else None

    header()
    for label in challengers:
        vs_b0 = [r for r in finals
                 if set(r["agents"]) == {label, "B0"}]
        mirror = [r for r in finals if r["agents"] == [label, label]]
        summarize(f"{label} vs B0", vs_b0, label)
        summarize(f"B0 vs {label}", vs_b0, "B0")
        summarize(f"{label} vs {label}", mirror, label)
    if len(challengers) == 2:
        a, b = challengers
        cross = [r for r in finals if set(r["agents"]) == {a, b}]
        summarize(f"{a} vs {b}", cross, a)
        summarize(f"{b} vs {a}", cross, b)

    bad = [(r["seed"], r["agents"], r["statuses"]) for r in finals
           if any(s != "DONE" for s in r["statuses"])]
    print(f"\nfinals bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in finals for p in r['players'])}")
    if base_f:
        print(f"finals records: {base_f}.json")
    print("B0 vs B0 at 32 seeds is E9; not rerun.")


if __name__ == "__main__":
    main()
