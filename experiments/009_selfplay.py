"""Step 8 - B_cow_sheep self-play and a larger paired sample.

The 8-seed round-robin never sat two cow/sheep farms on the same milk and wool
curves. Those products are thin (T=122 milk, T=105 wool) and one B farm already
harvests about 102 milk and 90 wool. This experiment asks whether that economy
survives a copy of itself, and whether B still beats the next family on a
larger, properly paired seed set.

Harness pairing, confirmed by inspection of research/harness.py before the sweep:

- `play()` puts `seed` into the engine configuration, so both seats share the
  weather and shop draws.
- `build_jobs(a, b, seeds, both_orders=True)` emits two jobs per seed:
  (a, b, seed, a_seat=0) and (b, a, seed, a_seat=1).
- Swapping two identical B specs is the same pairing twice, so the mirror uses
  `both_orders=False` and compares the two seats inside each episode.
- Cross-family matchups keep `both_orders=True`.

The previous round-robin already showed the pairing is working: on the same
seed and opponent, B's money usually matched across seats and the handful of
differences were a few hundred dollars, not family-sized.

Same seeds are used for the mirror and the two cross-family controls so B's
money can be compared under uncontested, partially contested, and fully
contested milk/wool without a seed confound.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SEEDS = range(32)
DEFAULTS = dict(routing="zone_nearest", hands_per_day=6)

FAMILIES = {
    "B_cow_sheep":   dict(geese=0, cows=3, sheep=3, crops=("WHEAT",)),
    "A_diversified": dict(geese=2, cows=2, sheep=2, crops=("WHEAT",)),
    "C_goose_wheat": dict(geese=4, crops=("WHEAT",)),
}

PRODUCTS = ("MILK", "WOOL", "EGG", "WHEAT")


def spec_for(label):
    params = dict(DEFAULTS)
    params.update(FAMILIES[label])
    return H.spec(label, **params)


def confirm_harness_pairing():
    """Assert the job builder pairs seeds and swaps seats the way the docstring says."""
    a, b = spec_for("B_cow_sheep"), spec_for("A_diversified")
    jobs = H.build_jobs(a, b, [42, 43], both_orders=True)
    assert len(jobs) == 4, jobs
    assert [j[2] for j in jobs] == [42, 42, 43, 43]
    assert [j[5] for j in jobs] == [0, 1, 0, 1]
    assert jobs[0][0].label == "B_cow_sheep" and jobs[0][1].label == "A_diversified"
    assert jobs[1][0].label == "A_diversified" and jobs[1][1].label == "B_cow_sheep"
    mirror = H.build_jobs(a, a, [0], both_orders=True)
    assert len(mirror) == 2
    assert mirror[0][0].label == mirror[0][1].label == "B_cow_sheep"
    print("harness pairing ok: same seeds, both seat orders. "
          "identical-agent swap is a duplicate pairing; mirror uses both_orders=False\n",
          flush=True)


def money_row(label, money, wins, losses, ties, margins):
    n = len(money)
    s = sorted(money)
    return (f"{label:<22}{n:>4}{wins:>5}{losses:>5}{ties:>5}"
            f"{wins / n if n else 0:>8.2f}"
            f"{statistics.fmean(s):>9,.0f}{statistics.median(s):>9,.0f}"
            f"{s[max(0, int(0.1 * n) - 1)]:>8,.0f}"
            f"{s[min(n - 1, int(0.9 * n))]:>8,.0f}"
            f"{statistics.pstdev(s) if n > 1 else 0:>8,.0f}"
            f"{statistics.fmean(margins):>+9,.0f}")


def product_means(players):
    out = {}
    for item in PRODUCTS:
        out[item] = (
            statistics.fmean(p["harvested"].get(item, 0) for p in players),
            statistics.fmean(p["sell_requested"].get(item, 0) for p in players),
        )
    return out


def print_products(title, players):
    means = product_means(players)
    bits = [f"{item} harv={h:.1f} sell={s:.1f}" for item, (h, s) in means.items()]
    print(f"  {title}: " + "  ".join(bits))


def day_money(players, day):
    vals = []
    for p in players:
        series = p.get("money_by_day") or []
        if day < len(series):
            vals.append(series[day])
    return statistics.fmean(vals) if vals else 0.0


def summarize_matchup(title, records, focus):
    """Report `focus`'s seats in `records` (both seats when the names match)."""
    seats = [(r, s, r["players"][s]) for r in records for s in (0, 1)
             if r["players"][s]["name"] == focus]
    money = [r["money"][s] for r, s, _ in seats]
    margins = [r["money"][s] - r["money"][1 - s] for r, s, _ in seats]
    wins = sum(1 for r, s, _ in seats if r["winner"] == s)
    losses = sum(1 for r, s, _ in seats if r["winner"] == 1 - s)
    ties = sum(1 for r, s, _ in seats if r["winner"] is None)
    print(money_row(title, money, wins, losses, ties, margins))
    return [p for _, _, p in seats]


def main():
    confirm_harness_pairing()

    b = spec_for("B_cow_sheep")
    jobs = []
    jobs += H.build_jobs(b, b, SEEDS, both_orders=False)
    jobs += H.build_jobs(b, spec_for("A_diversified"), SEEDS, both_orders=True)
    jobs += H.build_jobs(b, spec_for("C_goose_wheat"), SEEDS, both_orders=True)

    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 16 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"self-play + paired controls: {len(SEEDS)} seeds, "
          f"{len(jobs)} episodes "
          f"(32 B-vs-B + 64 B-vs-A + 64 B-vs-C)\n", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "selfplay")

    mirror = [r for r in records
              if r["agents"] == ["B_cow_sheep", "B_cow_sheep"]]
    vs_a = [r for r in records if set(r["agents"]) == {"B_cow_sheep", "A_diversified"}]
    vs_c = [r for r in records if set(r["agents"]) == {"B_cow_sheep", "C_goose_wheat"}]

    header = (f"{'matchup':<22}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>8}"
              f"{'money':>9}{'median':>9}{'p10':>8}{'p90':>8}{'sd':>8}{'margin':>9}")
    print("\n" + header)
    print("-" * len(header))

    m_players = summarize_matchup("B vs B (each seat)", mirror, "B_cow_sheep")
    summarize_matchup("B vs A", vs_a, "B_cow_sheep")
    summarize_matchup("A vs B", vs_a, "A_diversified")
    summarize_matchup("B vs C", vs_c, "B_cow_sheep")
    summarize_matchup("C vs B", vs_c, "C_goose_wheat")

    # ---- first mover / seat inside the mirror
    s0 = [r["money"][0] for r in mirror]
    s1 = [r["money"][1] for r in mirror]
    seat0_wins = sum(1 for r in mirror if r["winner"] == 0)
    seat1_wins = sum(1 for r in mirror if r["winner"] == 1)
    ties = sum(1 for r in mirror if r["winner"] is None)
    gaps = [a - b for a, b in zip(s0, s1)]
    print("\nmirror seat effect (same seed, identical configs)")
    print(f"  seat0 wins {seat0_wins}  seat1 wins {seat1_wins}  ties {ties}  "
          f"n={len(mirror)}")
    print(f"  mean money seat0 {statistics.fmean(s0):,.0f}  "
          f"seat1 {statistics.fmean(s1):,.0f}  "
          f"mean seat0-seat1 {statistics.fmean(gaps):+,.0f}  "
          f"median |gap| {statistics.median(abs(g) for g in gaps):,.0f}")

    # ---- product volumes
    print("\nproduct volumes (per seat)")
    print_products("B in mirror", m_players)
    print_products("B vs A", [r["players"][s] for r in vs_a for s in (0, 1)
                              if r["players"][s]["name"] == "B_cow_sheep"])
    print_products("A vs B", [r["players"][s] for r in vs_a for s in (0, 1)
                              if r["players"][s]["name"] == "A_diversified"])
    print_products("B vs C", [r["players"][s] for r in vs_c for s in (0, 1)
                              if r["players"][s]["name"] == "B_cow_sheep"])
    print_products("C vs B", [r["players"][s] for r in vs_c for s in (0, 1)
                              if r["players"][s]["name"] == "C_goose_wheat"])

    def episode_sold(recs, item):
        return [sum(p["sell_requested"].get(item, 0) for p in r["players"])
                for r in recs]

    print("\ncombined sell volume per episode (both farms)")
    for item in ("MILK", "WOOL"):
        print(f"  {item}: mirror {statistics.fmean(episode_sold(mirror, item)):.1f}  "
              f"B-vs-A {statistics.fmean(episode_sold(vs_a, item)):.1f}  "
              f"B-vs-C {statistics.fmean(episode_sold(vs_c, item)):.1f}")

    # ---- money path: does the contested market flatten late-game cash?
    print("\nB mean money by day")
    print(f"  {'day':<6}{'mirror':>10}{'vs A':>10}{'vs C':>10}")
    b_vs_a = [r["players"][s] for r in vs_a for s in (0, 1)
              if r["players"][s]["name"] == "B_cow_sheep"]
    b_vs_c = [r["players"][s] for r in vs_c for s in (0, 1)
              if r["players"][s]["name"] == "B_cow_sheep"]
    for day in (0, 8, 16, 24, 28):
        print(f"  {day:<6}{day_money(m_players, day):>10,.0f}"
              f"{day_money(b_vs_a, day):>10,.0f}"
              f"{day_money(b_vs_c, day):>10,.0f}")

    # ---- paired same-seed money: one B farm under the three opponent types
    print("\npaired B money on the same seed (one seat per condition, seat 0 of B)")
    by_seed = {}
    for r in mirror:
        by_seed.setdefault(r["seed"], {})["mirror"] = statistics.fmean(r["money"])
    for r in vs_a:
        for s in (0, 1):
            if r["players"][s]["name"] == "B_cow_sheep":
                by_seed.setdefault(r["seed"], {}).setdefault("vs_a", []).append(r["money"][s])
    for r in vs_c:
        for s in (0, 1):
            if r["players"][s]["name"] == "B_cow_sheep":
                by_seed.setdefault(r["seed"], {}).setdefault("vs_c", []).append(r["money"][s])
    deltas_a, deltas_c = [], []
    for seed, d in sorted(by_seed.items()):
        if "mirror" in d and "vs_a" in d and "vs_c" in d:
            deltas_a.append(d["mirror"] - statistics.fmean(d["vs_a"]))
            deltas_c.append(d["mirror"] - statistics.fmean(d["vs_c"]))
    if deltas_a:
        print(f"  mean (mirror - B-vs-A) {statistics.fmean(deltas_a):+,.0f}  "
              f"median {statistics.median(deltas_a):+,.0f}")
        print(f"  mean (mirror - B-vs-C) {statistics.fmean(deltas_c):+,.0f}  "
              f"median {statistics.median(deltas_c):+,.0f}")

    bad = [(r["seed"], r["agents"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    errs = sum(p["n_errors"] for r in records for p in r["players"])
    print(f"\nbad statuses: {bad or 'none'}   agent exceptions: {errs}")
    print(f"raw records: {base}.json")


if __name__ == "__main__":
    main()
