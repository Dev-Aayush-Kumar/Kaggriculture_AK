"""E3 - how much of the action budget does logistics eat, and does smarter
routing pay for its complexity?

Three assignment policies over an otherwise identical farm plan, on identical
seeds in both seat orders against a fixed opponent:

  nearest       global greedy over (unit, task) pairs by urgency then distance
  zone          farm split into contiguous bands, one unit per band, fixed order
  zone_nearest  same bands, but nearest-first inside the band

Then a crew-size sweep, because buying more hands is the obvious alternative to
routing cleverly and costs about $20 a day.
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import harness as H  # noqa: E402

SEEDS = range(5)
OPPONENT = "starter"
POLICIES = ("nearest", "zone", "zone_nearest")
CREWS = (2, 6, 10)

BASE = dict(geese=4, crops=("WHEAT",))

PRODUCTIVE = ("water", "plant", "harvest", "feed", "care", "fertilizer",
              "build", "clear", "fertilize")
LOGISTICS = ("logistics",)


def seats(records, label):
    for rec in records:
        for seat in (0, 1):
            if rec["players"][seat]["name"] == label:
                yield rec, seat, rec["players"][seat]


def profile(records, label):
    """Action budget and productivity, averaged over every seat this agent held."""
    rows = list(seats(records, label))
    n = len(rows)
    if not n:
        return None

    def mean(fn):
        return statistics.fmean(fn(rec, seat, p) for rec, seat, p in rows)

    def share(keys):
        return mean(lambda r, s, p: sum(p["categories"].get(k, 0) for k in keys)
                    / max(1, p["unit_turns"]))

    money = sorted(r["money"][s] for r, s, _ in rows)
    return {
        "label": label,
        "n": n,
        "money": statistics.fmean(money),
        "median": statistics.median(money),
        "p10": money[max(0, int(0.1 * n) - 1)],
        "p90": money[min(n - 1, int(0.9 * n))],
        "wins": sum(1 for r, s, _ in rows if r["winner"] == s),
        "unit_turns": mean(lambda r, s, p: p["unit_turns"]),
        "move": share(("move",)),
        "produce": share(PRODUCTIVE),
        "logistics": share(LOGISTICS),
        "idle": share(("idle",)),
        "wasted": share(("wasted",)),
        "travel": mean(lambda r, s, p: p["travel"]),
        "harvested": mean(lambda r, s, p: p["harvested_units"]),
        "fertilizer": mean(lambda r, s, p: p["fertilizer_collected"]),
        "per_unit_turn": mean(lambda r, s, p: p["harvested_units"] / max(1, p["unit_turns"])),
        "money_per_unit_turn": mean(lambda r, s, p: r["money"][s] / max(1, p["unit_turns"])),
        "deaths": mean(lambda r, s, p: p["drought_deaths"] + p["decay_deaths"]),
        "escaped": mean(lambda r, s, p: p["animals_escaped"]),
        "overflow": mean(lambda r, s, p: p["shed_overflow"]),
        "p99_ms": max(p["latency_p99_ms"] for _, _, p in rows),
    }


HEADER = (f"{'policy':<14}{'n':>3}{'money':>9}{'median':>9}{'p10':>8}{'p90':>8}"
          f"{'move':>7}{'prod':>7}{'logi':>7}{'idle':>7}"
          f"{'travel':>8}{'harv':>7}{'$/turn':>8}{'lost':>6}")


def line(r):
    return (f"{r['label']:<14}{r['n']:>3}{r['money']:>9,.0f}{r['median']:>9,.0f}"
            f"{r['p10']:>8,.0f}{r['p90']:>8,.0f}"
            f"{r['move']:>7.1%}{r['produce']:>7.1%}{r['logistics']:>7.1%}{r['idle']:>7.1%}"
            f"{r['travel']:>8,.0f}{r['harvested']:>7,.0f}"
            f"{r['money_per_unit_turn']:>8.1f}{r['deaths'] + r['escaped']:>6.1f}")


def run(label_specs, tag):
    jobs = []
    for label, params in label_specs:
        jobs += H.build_jobs(H.spec(label, **params), OPPONENT, SEEDS)
    t0 = time.perf_counter()
    done = [0]

    def progress(rec, i, total):
        done[0] = i
        if i % 5 == 0 or i == total:
            print(f"    {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"  running {len(jobs)} episodes...", flush=True)
    records = H.run_jobs(jobs, progress=progress)
    H.save(records, tag)
    return records


def main():
    print("E3a: routing policy, crew of 6, 4 geese + wheat, vs starter\n")
    recs = run([(p, dict(BASE, routing=p, hands_per_day=6)) for p in POLICIES],
               "e3-routing")
    print("\n" + HEADER)
    print("-" * len(HEADER))
    profiles = [profile(recs, p) for p in POLICIES]
    for r in profiles:
        print(line(r))

    best = max(profiles, key=lambda r: r["money"])
    worst = min(profiles, key=lambda r: r["money"])
    gap = best["money"] - worst["money"]
    print(f"\n  best={best['label']} worst={worst['label']}  "
          f"gap=${gap:,.0f} ({gap / max(1, worst['money']):.1%} of worst)")

    print(f"\n\nE3b: crew size at routing={best['label']}\n")
    recs2 = run([(f"crew{n}", dict(BASE, routing=best["label"], hands_per_day=n))
                 for n in CREWS], "e3-crew")
    print("\n" + HEADER)
    print("-" * len(HEADER))
    for n in CREWS:
        print(line(profile(recs2, f"crew{n}")))


if __name__ == "__main__":
    main()
