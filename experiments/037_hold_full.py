"""E36/E37 - hold-full on H1, targeting shed-forced residual wool.

H0 is P1-S. H1 is harvest-defer only. H2 also holds full tiles at a poor
quote until the existing last-day force. 8-seed screen of all three pairs.
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
H1 = dict(B.P1_S, harvest_defer_enabled=True)
H2 = dict(H1, harvest_defer_hold_full=True)


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
    milk_h = fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows)
    wool_h = fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold_m = fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    move = fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    lost = fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                 for _, _, p in rows)
    animals = fmean(p.get("animal_count", 0) for _, _, p in rows)
    print(f"{title:<12}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  milk h/rev/floor={milk_h:.1f}/{milk_r:,.0f}/{milk_f:.1f}"
          f"  wool={wool_h:.1f}/{wool_r:,.0f}/{wool_f:.1f}"
          f"  unsold m/w={unsold_m:.1f}/{unsold_w:.1f}")
    print(f"  animals={animals:.2f} move={move:.3f} idle={idle:.3f} lost={lost:.2f}")
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n,
        "mean": statistics.fmean(money), "p10": pct(money, 0.10),
        "median": statistics.median(money), "lost": lost, "wool_floor": wool_f,
    }


def promising(h2, h1):
    """H2 must not give back H1's P(win), and must help p10 or the wool tail."""
    record_ok = h2["wins"] >= h2["losses"]
    p10_ok = h2["p10"] >= h1["p10"] * 0.97
    better_tail = h2["p10"] > h1["p10"]
    better_wool = h2["wool_floor"] < h1["wool_floor"]
    reliable = h2["lost"] <= h1["lost"] + 0.5
    return record_ok and p10_ok and reliable and (better_tail or better_wool)


def run_pair(a_label, a_params, b_label, b_params, seeds, tag):
    jobs = H.build_jobs(H.spec(a_label, **a_params), H.spec(b_label, **b_params),
                        seeds, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: {a_label} vs {b_label}, {len(seeds)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))
    a = summarize(f"{a_label} vs {b_label}", records, a_label)
    b = summarize(f"{b_label} vs {a_label}", records, b_label)
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")
    return a, b


def main():
    print("E37 screen\n")
    h2_h1, h1_h2 = run_pair("H2", H2, "H1", H1, SCREEN_SEEDS, "e37-h2-h1")
    print()
    h2_p, p_h2 = run_pair("H2", H2, "P1S", P1S, SCREEN_SEEDS, "e37-h2-p1s")
    print()
    h1_p, p_h1 = run_pair("H1", H1, "P1S", P1S, SCREEN_SEEDS, "e37-h1-p1s")
    print("\nE37 screen summary")
    print(f"  H2 vs H1  {h2_h1['wins']}-{h2_h1['losses']}-{h2_h1['ties']}"
          f"  p10 {h2_h1['p10']:.0f} vs {h1_h2['p10']:.0f}"
          f"  wool$1 {h2_h1['wool_floor']:.1f} vs {h1_h2['wool_floor']:.1f}")
    print(f"  H2 vs P1S {h2_p['wins']}-{h2_p['losses']}-{h2_p['ties']}"
          f"  p10 {h2_p['p10']:.0f} vs {p_h2['p10']:.0f}")
    print(f"  H1 vs P1S {h1_p['wins']}-{h1_p['losses']}-{h1_p['ties']}"
          f"  p10 {h1_p['p10']:.0f} vs {p_h1['p10']:.0f}")
    if not promising(h2_h1, h1_h2):
        print("\nE37 screen: H2 does not improve H1 on the decision criteria. "
              "Hold-full hypothesis stops here.")
        return
    print("\nE37 screen looks directional; expanding H2 vs H1 to 32 seeds.\n")
    run_pair("H2", H2, "H1", H1, FINAL_SEEDS, "e38-finals")


if __name__ == "__main__":
    main()
