"""E40 - H1 vs P1-S day-level traces. No strategy change.

8 seeds, both seats. Uses existing probe fields plus hour-0 livestock/shed
snapshots. Prints when cash and animals diverge, and whether H1 losses
cluster in particular states.
"""

import os
import statistics
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.econ.tables import ANIMALS, MARKET_PARAMS  # noqa: E402

SEEDS = range(8)
H1 = dict(B.P1_S, harvest_defer_enabled=True)
WOOL_POOR = MARKET_PARAMS["WOOL"]["base"] * H.FLOOR_FRAC


def livestock_capital(animals):
    return (animals.get("COW", 0) * ANIMALS["COW"]["cost"]
            + animals.get("SHEEP", 0) * ANIMALS["SHEEP"]["cost"]
            + animals.get("GOOSE", 0) * ANIMALS["GOOSE"]["cost"])


def pair_rows(records):
    """One row per episode: H1 seat vs P1-S seat on the same board."""
    out = []
    for r in records:
        names = [p["name"] for p in r["players"]]
        if "H1" not in names or "P1S" not in names:
            continue
        h = names.index("H1")
        p = 1 - h
        out.append((r, h, p, r["players"][h], r["players"][p]))
    return out


def pad(xs, n, fill=0):
    xs = list(xs or [])
    return xs + [fill] * max(0, n - len(xs))


def mean_series(series_list, fill=0.0):
    if not series_list:
        return []
    n = max(len(s) for s in series_list)
    out = []
    for i in range(n):
        vals = [s[i] for s in series_list if i < len(s)]
        out.append(statistics.fmean(vals) if vals else fill)
    return out


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def summarize_match(records):
    rows = pair_rows(records)
    n = len(rows)
    h_money = [r["money"][h] for r, h, _, _, _ in rows]
    p_money = [r["money"][p] for r, _, p, _, _ in rows]
    wins = sum(1 for r, h, _, _, _ in rows if r["winner"] == h)
    losses = sum(1 for r, h, _, _, _ in rows if r["winner"] == 1 - h)
    ties = n - wins - losses
    print(f"\nH1 vs P1S  n={n}  {wins}-{losses}-{ties}  "
          f"H1 mean {statistics.fmean(h_money):,.0f}  p10 {pct(h_money, 0.10):,.0f}  "
          f"P1S mean {statistics.fmean(p_money):,.0f}  p10 {pct(p_money, 0.10):,.0f}")
    return rows


def print_day_table(title, h_series, p_series, days=(0, 5, 10, 15, 20, 25, 29)):
    print(f"\n{title}")
    print(f"{'day':>4}{'H1':>10}{'P1S':>10}{'gap':>10}")
    n = max(len(h_series), len(p_series))
    for d in days:
        if d >= n:
            continue
        h = h_series[d] if d < len(h_series) else 0
        p = p_series[d] if d < len(p_series) else 0
        print(f"{d:>4}{h:>10.1f}{p:>10.1f}{h - p:>10.1f}")


def first_lead_day(h_money, p_money, persist=2):
    """First day H1 is ahead and stays ahead for `persist` days."""
    n = min(len(h_money), len(p_money))
    for d in range(n):
        if all(h_money[i] > p_money[i] for i in range(d, min(n, d + persist))):
            return d
    return None


def analyze(records):
    rows = summarize_match(records)
    h_cash = [pad(hp.get("money_by_day"), 30) for _, _, _, hp, _ in rows]
    p_cash = [pad(pp.get("money_by_day"), 30) for _, _, _, _, pp in rows]
    h_ani = [pad(hp.get("animals_by_day"), 30) for _, _, _, hp, _ in rows]
    p_ani = [pad(pp.get("animals_by_day"), 30) for _, _, _, _, pp in rows]
    h_shed = [pad([s.get("used", 0) for s in (hp.get("shed_by_day") or [])], 30)
              for _, _, _, hp, _ in rows]
    p_shed = [pad([s.get("used", 0) for s in (pp.get("shed_by_day") or [])], 30)
              for _, _, _, _, pp in rows]
    h_wool_shed = [pad([s.get("WOOL", 0) for s in (hp.get("shed_by_day") or [])], 30)
                   for _, _, _, hp, _ in rows]
    h_wool_tile = [pad([s.get("WOOL", 0) for s in (hp.get("tile_held_by_day") or [])], 30)
                   for _, _, _, hp, _ in rows]
    p_wool_tile = [pad([s.get("WOOL", 0) for s in (pp.get("tile_held_by_day") or [])], 30)
                   for _, _, _, _, pp in rows]

    print_day_table("cash by day (mean)", mean_series(h_cash), mean_series(p_cash))
    print_day_table("animals by day (mean)", mean_series(h_ani), mean_series(p_ani))
    print_day_table("shed used by day (mean)", mean_series(h_shed), mean_series(p_shed))
    print_day_table("H1 vs P1S wool on tile (mean)",
                    mean_series(h_wool_tile), mean_series(p_wool_tile))

    leads = [first_lead_day(hm, pm) for hm, pm in zip(h_cash, p_cash)]
    known = [d for d in leads if d is not None]
    print(f"\nH1 first sustained cash lead: "
          f"{'none' if not known else f'median day {statistics.median(known):.0f}'}  "
          f"({len(known)}/{len(leads)} episodes)")

    wins = [(r, hp, pp) for r, h, p, hp, pp in rows if r["winner"] == h]
    losses = [(r, hp, pp) for r, h, p, hp, pp in rows if r["winner"] == 1 - h]
    ties = [(r, hp, pp) for r, h, p, hp, pp in rows if r["winner"] is None]
    print(f"outcomes: wins={len(wins)} losses={len(losses)} ties={len(ties)}")

    def blob(title, group):
        if not group:
            print(f"\n{title}: none")
            return
        h_m = [r["money"][0 if r["players"][0]["name"] == "H1" else 1] for r, hp, pp in group]
        # money from record via names
        hm, pm, lost_h, lost_p, ani_h, ani_p = [], [], [], [], [], []
        wool_h, wool_p, floor_h, floor_p, esc_h, esc_p = [], [], [], [], [], []
        poor_w, rescue_w, idle_h, move_h, cap_h, cap_p = [], [], [], [], [], []
        for r, hp, pp in group:
            hm.append(r["money"][0 if r["players"][0]["name"] == "H1" else 1])
            pm.append(r["money"][1 if r["players"][0]["name"] == "H1" else 0])
            lost_h.append(hp["drought_deaths"] + hp["decay_deaths"] + hp["animals_escaped"])
            lost_p.append(pp["drought_deaths"] + pp["decay_deaths"] + pp["animals_escaped"])
            ani_h.append(hp.get("animal_count", 0))
            ani_p.append(pp.get("animal_count", 0))
            wool_h.append(hp.get("harvested", {}).get("WOOL", 0))
            wool_p.append(pp.get("harvested", {}).get("WOOL", 0))
            floor_h.append(hp.get("sell_floor_units", {}).get("WOOL", 0))
            floor_p.append(pp.get("sell_floor_units", {}).get("WOOL", 0))
            esc_h.extend(hp.get("escape_days") or [])
            esc_p.extend(pp.get("escape_days") or [])
            quotes = hp.get("price_by_day") or []
            poor_w.append(sum(1 for q in quotes if (q.get("WOOL") or 999) < WOOL_POOR))
            rescue_w.append(sum(hv["qty"] for hv in (hp.get("harvest_events") or [])
                                if hv["item"] == "WOOL" and H.harvest_is_rescue(hv)))
            idle_h.append(hp.get("category_share", {}).get("idle", 0))
            move_h.append(hp.get("category_share", {}).get("move", 0))
            cap_h.append(livestock_capital(hp.get("animals") or {}))
            cap_p.append(livestock_capital(pp.get("animals") or {}))
        print(f"\n{title} n={len(group)}")
        print(f"  cash H1/P1S {statistics.fmean(hm):,.0f}/{statistics.fmean(pm):,.0f}")
        print(f"  animals {statistics.fmean(ani_h):.2f}/{statistics.fmean(ani_p):.2f}  "
              f"lost {statistics.fmean(lost_h):.2f}/{statistics.fmean(lost_p):.2f}")
        print(f"  livestock capital {statistics.fmean(cap_h):,.0f}/{statistics.fmean(cap_p):,.0f}")
        print(f"  wool harvest {statistics.fmean(wool_h):.1f}/{statistics.fmean(wool_p):.1f}  "
              f"floor {statistics.fmean(floor_h):.1f}/{statistics.fmean(floor_p):.1f}  "
              f"rescue {statistics.fmean(rescue_w):.1f}")
        print(f"  wool-poor days {statistics.fmean(poor_w):.1f}  "
              f"idle {statistics.fmean(idle_h):.3f}  move {statistics.fmean(move_h):.3f}")
        print(f"  H1 escape days {dict(Counter(esc_h)) or 'none'}  "
              f"P1S {dict(Counter(esc_p)) or 'none'}")

    blob("H1 wins", wins)
    blob("H1 losses", losses)
    blob("ties", ties)

    print("\nper-episode cash lead / animals / wool floor")
    print(f"{'seed':>5}{'seat':>5}{'res':>5}{'H1$':>8}{'P1$':>8}{'lead':>6}"
          f"{'H1a':>5}{'P1a':>5}{'Hl':>4}{'Pl':>4}{'Hf':>5}{'Pf':>5}")
    for r, h, p, hp, pp in rows:
        res = "W" if r["winner"] == h else ("L" if r["winner"] == 1 - h else "T")
        lead = first_lead_day(pad(hp.get("money_by_day"), 30),
                              pad(pp.get("money_by_day"), 30))
        print(f"{r['seed']:>5}{h:>5}{res:>5}{r['money'][h]:>8.0f}{r['money'][p]:>8.0f}"
              f"{str(lead) if lead is not None else '-':>6}"
              f"{hp.get('animal_count', 0):>5}{pp.get('animal_count', 0):>5}"
              f"{hp['drought_deaths'] + hp['decay_deaths'] + hp['animals_escaped']:>4}"
              f"{pp['drought_deaths'] + pp['decay_deaths'] + pp['animals_escaped']:>4}"
              f"{hp.get('sell_floor_units', {}).get('WOOL', 0):>5.0f}"
              f"{pp.get('sell_floor_units', {}).get('WOOL', 0):>5.0f}")


def main():
    jobs = H.build_jobs(H.spec("H1", **H1), H.spec("P1S", **B.P1_S),
                        SEEDS, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E40 trace: H1 vs P1-S, {len(SEEDS)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e40-trace")
    analyze(records)
    print(f"\nraw records: {base}.json")


if __name__ == "__main__":
    main()
