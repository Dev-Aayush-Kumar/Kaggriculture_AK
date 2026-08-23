"""E28 - endgame liquidation sweep around P1-S.

L0 is unchanged P1-S (force_days=0). Candidates only retune the existing
sell_defer_force_days / shed_frac surface. sale_qty stays off.
8-seed paired screen vs L0, then at most two finalists on 32 seeds.
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
LAST_DAY = 29  # (720 - 2) // 24; E7 last actionable day

# L1: slightly less aggressive shed override (likely rare; capacity is 100).
# L2: never time-force a poor quote (hold through the last day unless shed-full).
# L3: force one day earlier (last two days), the symmetric more-aggressive control.
CANDIDATES = {
    "L1": dict(B.P1_S, sell_defer_shed_frac=1.0),
    "L2": dict(B.P1_S, sell_defer_force_days=-1),
    "L3": dict(B.P1_S, sell_defer_force_days=1),
}


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


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def mean_sale_day(player, item):
    by_day = player.get("sell_qty_by_day", {}).get(item) or {}
    total = sum(by_day.values())
    if not total:
        return None
    return sum(int(d) * q for d, q in by_day.items()) / total


def sold_on_or_after(player, item, day):
    by_day = player.get("sell_qty_by_day", {}).get(item) or {}
    return sum(q for d, q in by_day.items() if int(d) >= day)


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    if not n:
        print(f"{title:<14} n=0")
        return None
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    milk_h = fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows)
    wool_h = fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_s = fmean(p.get("sell_requested", {}).get("MILK", 0) for _, _, p in rows)
    wool_s = fmean(p.get("sell_requested", {}).get("WOOL", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    milk_f = fmean(p.get("sell_floor_units", {}).get("MILK", 0) for _, _, p in rows)
    wool_f = fmean(p.get("sell_floor_units", {}).get("WOOL", 0) for _, _, p in rows)
    unsold_m = fmean(p.get("final_shed", {}).get("MILK", 0) for _, _, p in rows)
    unsold_w = fmean(p.get("final_shed", {}).get("WOOL", 0) for _, _, p in rows)
    animals = fmean(p.get("animal_count", 0) for _, _, p in rows)
    move = fmean(p["category_share"].get("move", 0) for _, _, p in rows)
    idle = fmean(p["category_share"].get("idle", 0) for _, _, p in rows)
    lost = fmean(p["drought_deaths"] + p["decay_deaths"] + p["animals_escaped"]
                 for _, _, p in rows)
    wall = fmean(r["wall_seconds"] for r, _, _ in rows)
    last_m = fmean(sold_on_or_after(p, "MILK", LAST_DAY) for _, _, p in rows)
    last_w = fmean(sold_on_or_after(p, "WOOL", LAST_DAY) for _, _, p in rows)
    liq_m = fmean(sold_on_or_after(p, "MILK", LAST_DAY - 1) for _, _, p in rows)
    liq_w = fmean(sold_on_or_after(p, "WOOL", LAST_DAY - 1) for _, _, p in rows)
    print(f"{title:<14}{n:>4}{wins:>5}{losses:>5}{ties:>5}{wins / n:>7.2f}"
          f"{statistics.fmean(money):>9,.0f}{statistics.median(money):>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}{pct(money, 0.90):>8,.0f}"
          f"{statistics.pstdev(money) if n > 1 else 0:>8,.0f}")
    print(f"  milk h/s/rev/px/floor={milk_h:.1f}/{milk_s:.1f}/{milk_r:,.0f}/"
          f"{(milk_r / milk_s) if milk_s else 0:.1f}/{milk_f:.1f}"
          f"  wool={wool_h:.1f}/{wool_s:.1f}/{wool_r:,.0f}/"
          f"{(wool_r / wool_s) if wool_s else 0:.1f}/{wool_f:.1f}")
    print(f"  unsold m/w={unsold_m:.1f}/{unsold_w:.1f}  last-day s m/w="
          f"{last_m:.1f}/{last_w:.1f}  d28+ s m/w={liq_m:.1f}/{liq_w:.1f}"
          f"  sale day m/w="
          f"{fmean(mean_sale_day(p, 'MILK') for _, _, p in rows):.1f}/"
          f"{fmean(mean_sale_day(p, 'WOOL') for _, _, p in rows):.1f}")
    print(f"  animals={animals:.2f} move={move:.3f} idle={idle:.3f} "
          f"lost={lost:.2f} wall={wall:.1f}s")
    return {
        "label": label, "wins": wins, "losses": losses, "ties": ties,
        "rate": wins / n, "mean": statistics.fmean(money),
        "median": statistics.median(money), "p10": pct(money, 0.10),
        "p25": pct(money, 0.25), "wool_floor": wool_f, "milk_floor": milk_f,
        "unsold_w": unsold_w, "lost": lost,
    }


def promising(cand, l0):
    better_record = cand["wins"] > cand["losses"]
    better_tail = cand["p10"] > l0["p10"]
    p10_ok = cand["p10"] >= l0["p10"] * 0.97
    reliable = cand["lost"] <= l0["lost"] + 0.5
    return (better_record or better_tail) and p10_ok and reliable


def header():
    h = (f"{'matchup':<14}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
         f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}{'sd':>8}")
    print("\n" + h)
    print("-" * len(h))


def run_pair(label, params, seeds, tag):
    jobs = H.build_jobs(spec(label, params), spec("L0", B.P1_S),
                        seeds, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"{tag}: {label} vs L0, {len(seeds)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, tag)
    header()
    cand = summarize(f"{label} vs L0", records, label)
    l0 = summarize("L0 vs " + label, records, "L0")
    bad = [(r["seed"], r["statuses"]) for r in records
           if any(s != "DONE" for s in r["statuses"])]
    print(f"bad statuses: {bad or 'none'}  "
          f"exceptions: {sum(p['n_errors'] for r in records for p in r['players'])}")
    print(f"raw records: {base}.json")
    return cand, l0


def rank_key(row):
    cand, _l0 = row
    return (cand["wins"] - cand["losses"], cand["p10"], cand["median"], cand["mean"])


def main():
    screen = []
    for label, params in CANDIDATES.items():
        cand, l0 = run_pair(label, params, SCREEN_SEEDS, f"e28-screen-{label}")
        ok = promising(cand, l0)
        screen.append((cand, l0, ok))
        print(f"screen {label}: {'promising' if ok else 'not promising'}\n")

    viable = [(c, p) for c, p, ok in screen if ok]
    viable.sort(key=rank_key, reverse=True)
    finalists = viable[:2]
    print("finalists:", [c["label"] for c, _ in finalists] or "none")
    if not finalists:
        print("E28: no liquidation candidate beat L0/P1-S on the screen.")
        return
    for cand, _l0 in finalists:
        run_pair(cand["label"], CANDIDATES[cand["label"]], FINAL_SEEDS,
                 f"e28-finals-{cand['label']}")


if __name__ == "__main__":
    main()
