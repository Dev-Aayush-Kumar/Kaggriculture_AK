"""E49/E50 - screen the E48 on-tile last-day rescue.

H4 = H3 + endgame_rescue_feed. P1-S, H1, and H3 stay at the default off.
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
H3 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True)
H4 = dict(H3, endgame_rescue_feed=True)


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


def late_escapes(p):
    n = 0
    for ev in p.get("escape_events") or []:
        if ev.get("loss_day", -1) >= 28 or ev.get("obs_day", -1) >= 29:
            n += 1
    if n:
        return n
    return sum(1 for d in p.get("escape_days") or [] if d >= 29)


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    milk_h = fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows)
    wool_h = fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold = fmean(p.get("unsold_units", 0) for _, _, p in rows)
    move = fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    escaped = fmean(p.get("animals_escaped", 0) for _, _, p in rows)
    late = fmean(late_escapes(p) for _, _, p in rows)
    animals = fmean(p.get("animal_count", 0) for _, _, p in rows)
    wall = fmean(r.get("wall_seconds", 0) for r, _, _ in rows)
    bad = sum(1 for r, s, _ in rows if r["statuses"][s] not in ("DONE", "OK", None)
              and r["statuses"][s] != 0)
    errors = sum(p.get("n_errors", 0) for _, _, p in rows)
    print(f"{title:<12}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  milk h/rev/floor={milk_h:.1f}/{milk_r:,.0f}/{milk_f:.1f}"
          f"  wool={wool_h:.1f}/{wool_r:,.0f}/{wool_f:.1f}"
          f"  unsold={unsold:.1f}")
    print(f"  animals={animals:.2f} escaped={escaped:.2f} late={late:.2f}"
          f"  move={move:.3f} idle={idle:.3f} wall={wall:.1f}s"
          f"  bad={bad} errors={errors}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n,
        "mean": statistics.fmean(money), "median": statistics.median(money),
        "p10": pct(money, 0.10), "p25": pct(money, 0.25),
        "escaped": escaped, "late": late, "animals": animals,
    }


def screen_ok(h4_h3, h3_h4, h4_p, p_h4):
    """Stop if H4 clearly loses P(win) to H3 or P1-S."""
    vs_h3 = h4_h3["wins"] >= h4_h3["losses"]
    vs_p = h4_p["wins"] >= h4_p["losses"]
    p10_ok = h4_h3["p10"] >= h3_h4["p10"] * 0.97 and h4_p["p10"] >= p_h4["p10"] * 0.97
    return vs_h3 and vs_p and p10_ok


def finals_promote(h4_h3, h3_h4, h4_p, p_h4):
    """H4 must improve on both H3 and P1-S without harming the lower tail."""
    beat_h3 = h4_h3["wins"] > h4_h3["losses"]
    beat_p = h4_p["wins"] > h4_p["losses"]
    tail_h3 = h4_h3["p10"] >= h3_h4["p10"] and h4_h3["p25"] >= h3_h4["p25"]
    tail_p = h4_p["p10"] >= p_h4["p10"] and h4_p["p25"] >= p_h4["p25"]
    return beat_h3 and beat_p and tail_h3 and tail_p


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
    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))
    a = summarize(f"{a_label} vs {b_label}", records, a_label)
    b = summarize(f"{b_label} vs {a_label}", records, b_label)
    print(f"raw records: {base}.json")
    return a, b


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "screen"
    print(f"E49/E50 rescue {stage}\n")
    if stage == "screen":
        h4_h3, h3_h4 = run_pair("H4", H4, "H3", H3, SCREEN_SEEDS, "e49-h4-h3")
        print()
        h4_p, p_h4 = run_pair("H4", H4, "P1S", P1S, SCREEN_SEEDS, "e49-h4-p1s")
        print("\nE49 screen summary")
        print(f"  H4 vs H3  {h4_h3['wins']}-{h4_h3['losses']}-{h4_h3['ties']}"
              f"  p10 {h4_h3['p10']:.0f} vs {h3_h4['p10']:.0f}"
              f"  late {h4_h3['late']:.2f} vs {h3_h4['late']:.2f}")
        print(f"  H4 vs P1S {h4_p['wins']}-{h4_p['losses']}-{h4_p['ties']}"
              f"  p10 {h4_p['p10']:.0f} vs {p_h4['p10']:.0f}"
              f"  late {h4_p['late']:.2f} vs {p_h4['late']:.2f}")
        if not screen_ok(h4_h3, h3_h4, h4_p, p_h4):
            print("\nE49: H4 does not survive the screen. Stop.")
            return
        print("\nE49 screen survived. Run: python experiments/049_rescue.py finals")
        return
    if stage == "finals":
        h4_h3, h3_h4 = run_pair("H4", H4, "H3", H3, FINAL_SEEDS, "e50-h4-h3")
        print()
        h4_p, p_h4 = run_pair("H4", H4, "P1S", P1S, FINAL_SEEDS, "e50-h4-p1s")
        print("\nE50 finals summary")
        print(f"  H4 vs H3  {h4_h3['wins']}-{h4_h3['losses']}-{h4_h3['ties']}"
              f"  p10 {h4_h3['p10']:.0f} vs {h3_h4['p10']:.0f}"
              f"  p25 {h4_h3['p25']:.0f} vs {h3_h4['p25']:.0f}")
        print(f"  H4 vs P1S {h4_p['wins']}-{h4_p['losses']}-{h4_p['ties']}"
              f"  p10 {h4_p['p10']:.0f} vs {p_h4['p10']:.0f}"
              f"  p25 {h4_p['p25']:.0f} vs {p_h4['p25']:.0f}")
        if not finals_promote(h4_h3, h3_h4, h4_p, p_h4):
            print("\nE50: H4 does not clearly improve on both. Skip E51.")
            return
        print("\nE50: H4 improved on both. Field validation would be next.")
        return
    raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
