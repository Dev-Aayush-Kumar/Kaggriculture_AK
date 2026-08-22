"""E15 - one sell-timing rule on top of B2, not stacked on P1.

P0 is B2. P2 is the same Config plus sell_defer_enabled: a quote below
sell_floor_fraction is held even inside the original 2-day liquidation window,
unless remaining days are at or below sell_defer_force_days or the shed is
approaching capacity.

16-seed paired screen first; expand to 32 only if P2 is directionally better
on P(win) or money without a material p10 hit.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SCREEN_SEEDS = range(16)
FINAL_SEEDS = range(32)

P0 = dict(routing="zone_nearest", geese=0, cows=3, sheep=3, crops=("WHEAT",),
          hands_per_day=6, livestock_cap_enabled=True)
P2 = dict(P0, sell_defer_enabled=True)


def spec(label, params):
    return H.spec(label, **params)


def seats(records, label):
    return [(r, s, r["players"][s]) for r in records for s in (0, 1)
            if r["players"][s]["name"] == label]


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def mean_sale_day(player, item):
    by_day = player.get("sell_qty_by_day", {}).get(item) or {}
    total = sum(by_day.values())
    if not total:
        return None
    return sum(int(d) * q for d, q in by_day.items()) / total


def band_price(player, item, lo, hi):
    rows = [row.get(item) for i, row in enumerate(player.get("price_by_day") or [])
            if lo <= i < hi and row.get(item) is not None]
    return statistics.fmean(rows) if rows else None


def realized(player, item):
    harvested = player.get("harvested", {}).get(item, 0)
    revenue = player.get("sell_revenue", {}).get(item, 0)
    if harvested <= 0:
        return None
    return revenue / harvested


def extra(rows):
    def fmean(xs):
        xs = [x for x in xs if x is not None]
        return statistics.fmean(xs) if xs else 0.0

    milk_rev = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_rev = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold = fmean(p["unsold_units"] for _, _, p in rows)
    unsold_m = fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    move = fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    prod = 1.0 - move - idle
    lost = fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                 for _, _, p in rows)
    print(f"  move={move:.3f} prod={prod:.3f} idle={idle:.3f} lost={lost:.2f}"
          f"  milk rev/floor={milk_rev:,.0f}/{milk_f:.1f}"
          f"  wool={wool_rev:,.0f}/{wool_f:.1f} unsold={unsold:.1f}"
          f" (milk={unsold_m:.1f} wool={unsold_w:.1f})")
    print(f"  milk $/unit={fmean(realized(p, 'MILK') for _, _, p in rows):.1f}"
          f"  wool $/unit={fmean(realized(p, 'WOOL') for _, _, p in rows):.1f}"
          f"  sale day milk={fmean(mean_sale_day(p, 'MILK') for _, _, p in rows):.1f}"
          f"  wool={fmean(mean_sale_day(p, 'WOOL') for _, _, p in rows):.1f}")
    print(f"  milk quote d0-9/10-19/20+="
          f"{fmean(band_price(p, 'MILK', 0, 10) for _, _, p in rows):.0f}/"
          f"{fmean(band_price(p, 'MILK', 10, 20) for _, _, p in rows):.0f}/"
          f"{fmean(band_price(p, 'MILK', 20, 40) for _, _, p in rows):.0f}"
          f"  wool="
          f"{fmean(band_price(p, 'WOOL', 0, 10) for _, _, p in rows):.0f}/"
          f"{fmean(band_price(p, 'WOOL', 10, 20) for _, _, p in rows):.0f}/"
          f"{fmean(band_price(p, 'WOOL', 20, 40) for _, _, p in rows):.0f}")


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    print(f"{title:<12}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    extra(rows)
    return {
        "wins": wins, "losses": losses, "ties": ties, "rate": wins / n,
        "mean": statistics.fmean(money), "p10": pct(money, 0.10),
        "median": statistics.median(money),
    }


def promising(p2, p0):
    """Directional: more wins than losses, or better money, without a p10 hit."""
    better_record = p2["wins"] > p2["losses"]
    better_money = p2["mean"] > p0["mean"] or p2["median"] > p0["median"]
    p10_ok = p2["p10"] >= p0["p10"] * 0.97
    return (better_record or better_money) and p10_ok


def header():
    h = (f"{'matchup':<12}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))


def run_pair(seeds, tag):
    jobs = H.build_jobs(spec("P2", P2), spec("P0", P0), seeds, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: P2 vs P0, {len(seeds)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    header()
    p2 = summarize("P2 vs P0", records, "P2")
    p0 = summarize("P0 vs P2", records, "P0")
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")
    return p2, p0


def main():
    p2, p0 = run_pair(SCREEN_SEEDS, "e15-screen")
    if not promising(p2, p0):
        print("\nE15 screen: P2 is not a credible improvement. "
              "Sell-timing hypothesis stops here; not expanded.")
        return
    print("\nE15 screen looks directional; expanding to 32 seeds.\n")
    run_pair(FINAL_SEEDS, "e15-finals")


if __name__ == "__main__":
    main()
