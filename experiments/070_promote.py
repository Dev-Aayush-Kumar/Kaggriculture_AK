"""E70 - Phase 18 H4 promotion / robustness packet. No strategy change.

GATE (locked before any new episode is run):

Promote H4 over P1-S as the official submission engine only if ALL hold:

1. Out-of-sample (seeds 32-63, both seats): H4 wins > losses and P(win) >= 0.60.
2. Combined with E50 (seeds 0-31): P(win) >= 0.70.
3. OOS and combined H4 p10 >= 0.97 * P1-S p10 (no material tail regression).
4. No new bad statuses / agent errors on H4 or P1-S in the OOS or field seats.
5. Compact field (seeds 100-107, both seats, E51 families):
   H4 wins >= losses against every family, and H4's total field wins are
   at least those of P1-S on the same seeds (non-inferior).

H4 does not need to eliminate known long wool-crash losses.
Do not promote if the OOS result reverses, collapses toward a coin-flip,
or the tail/reliability bar fails.

H4 vs H1 (seeds 200-207) is secondary and does not veto promotion.
"""

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.config import Config  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
E50_PATH = os.path.join(ROOT, "results", "e50-h4-p1s-20260824-041910.json")

OOS_SEEDS = range(32, 64)
FIELD_SEEDS = range(100, 108)
H1_SEEDS = range(200, 208)
WOOL_POOR = 60.0

P1S = dict(B.P1_S)
H4 = dict(B.H4)
H1 = dict(B.P1_S, harvest_defer_enabled=True)

FIELD = {
    "A_diversified":  dict(routing="zone_nearest", geese=2, cows=2, sheep=2,
                           crops=("WHEAT",), hands_per_day=6),
    "D_premium_crop": dict(routing="zone_nearest", geese=0,
                           crops=("STRAWBERRY", "MELON"), hands_per_day=8),
    "C_goose_wheat":  dict(routing="zone_nearest", geese=4, cows=0, sheep=0,
                           crops=("WHEAT",), hands_per_day=6),
    "reference":      dict(routing="zone_nearest", geese=4, cows=0, sheep=0,
                           crops=("WHEAT",), hands_per_day=6),
}


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


def poor_days(p):
    return sum(1 for q in (p.get("price_by_day") or [])
               if (q.get("WOOL") or 999) < WOOL_POOR)


def regime(n_poor):
    if n_poor >= 13:
        return "long_crash"
    if n_poor >= 10:
        return "poor_recovery"
    return "healthy"


def summarize(title, records, label):
    rows = seats(records, label)
    n = len(rows)
    money = [r["money"][s] for r, s, _ in rows]
    wins = sum(1 for r, s, _ in rows if r["winner"] == s)
    losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
    ties = n - wins - losses
    margins = [r["money"][s] - r["money"][1 - s] for r, s, _ in rows]
    close_loss = sum(1 for m in margins if -1000 <= m < 0)
    loss_margins = [m for m in margins if m < 0]
    wheat_h = fmean(p.get("harvested", {}).get("WHEAT", 0) for _, _, p in rows)
    milk_h = fmean(p.get("harvested", {}).get("MILK", 0) for _, _, p in rows)
    wool_h = fmean(p.get("harvested", {}).get("WOOL", 0) for _, _, p in rows)
    wheat_r = fmean(p.get("sell_revenue", {}).get("WHEAT", 0) for _, _, p in rows)
    milk_r = fmean(p.get("sell_revenue", {}).get("MILK", 0) for _, _, p in rows)
    wool_r = fmean(p.get("sell_revenue", {}).get("WOOL", 0) for _, _, p in rows)
    fert_r = fmean(p.get("sell_revenue", {}).get("FERTILIZER", 0) for _, _, p in rows)
    escaped = fmean(p.get("animals_escaped", 0) for _, _, p in rows)
    drought = fmean(p.get("drought_deaths", 0) for _, _, p in rows)
    bad = sum(1 for r, s, _ in rows
              if r["statuses"][s] not in ("DONE", "OK", None, 0))
    errors = sum(p.get("n_errors", 0) for _, _, p in rows)
    print(f"{title:<22}{n:>4}{wins:>5}{losses:>5}{ties:>5}"
          f"{(wins / n if n else 0):>7.3f}"
          f"{statistics.fmean(money) if n else 0:>9,.0f}"
          f"{statistics.median(money) if n else 0:>9,.0f}"
          f"{pct(money, 0.10):>8,.0f}{pct(money, 0.25):>8,.0f}"
          f"{pct(money, 0.90):>8,.0f}")
    print(f"  wheat_h={wheat_h:.1f} milk_h={milk_h:.1f} wool_h={wool_h:.1f}"
          f"  wheat_r={wheat_r:,.0f} milk_r={milk_r:,.0f} wool_r={wool_r:,.0f}"
          f" fert_r={fert_r:,.0f}")
    print(f"  escaped={escaped:.2f} drought={drought:.2f} close_loss={close_loss}"
          f" mean_margin={fmean(margins):,.0f} bad={bad} errors={errors}")
    return {
        "n": n, "wins": wins, "losses": losses, "ties": ties,
        "rate": wins / n if n else 0,
        "mean": statistics.fmean(money) if n else 0,
        "median": statistics.median(money) if n else 0,
        "p10": pct(money, 0.10), "p25": pct(money, 0.25), "p90": pct(money, 0.90),
        "mean_margin": fmean(margins),
        "median_margin": statistics.median(margins) if margins else 0,
        "min_margin": min(margins) if margins else 0,
        "max_margin": max(margins) if margins else 0,
        "close_loss": close_loss,
        "n_losses": len(loss_margins),
        "mean_loss_margin": fmean(loss_margins),
        "escaped": escaped, "drought": drought, "bad": bad, "errors": errors,
        "wheat_h": wheat_h, "milk_h": milk_h, "wool_h": wool_h,
        "wheat_r": wheat_r, "milk_r": milk_r, "wool_r": wool_r, "fert_r": fert_r,
    }


def dump_regimes(records, label):
    rows = seats(records, label)
    buckets = {"healthy": [], "poor_recovery": [], "long_crash": []}
    for r, s, p in rows:
        buckets[regime(poor_days(p))].append((r["winner"] == s, r["money"][s] - r["money"][1 - s]))
    print(f"  regimes for {label}:")
    for name, xs in buckets.items():
        if not xs:
            print(f"    {name}: n=0")
            continue
        w = sum(1 for won, _ in xs if won)
        print(f"    {name}: n={len(xs)} W-L {w}-{len(xs) - w} "
              f"P(win)={w / len(xs):.3f} mean_margin={fmean(m for _, m in xs):,.0f}")
    return {
        name: {
            "n": len(xs),
            "wins": sum(1 for won, _ in xs if won),
            "losses": sum(1 for won, _ in xs if not won),
            "rate": (sum(1 for won, _ in xs if won) / len(xs)) if xs else 0,
            "mean_margin": fmean(m for _, m in xs),
        }
        for name, xs in buckets.items()
    }


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
    hdr = (f"{'matchup':<22}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
           f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}")
    print("\n" + hdr)
    print("-" * len(hdr))
    a = summarize(f"{a_label} vs {b_label}", records, a_label)
    b = summarize(f"{b_label} vs {a_label}", records, b_label)
    dump_losses(records, a_label)
    dump_regimes(records, a_label)
    print(f"raw records: {base}.json")
    return a, b, records, base


def dump_losses(records, label):
    rows = seats(records, label)
    losses = []
    for r, s, p in rows:
        if r["winner"] != 1 - s:
            continue
        m = r["money"][s] - r["money"][1 - s]
        n_poor = poor_days(p)
        losses.append((r["seed"], s, m, n_poor, regime(n_poor)))
    losses.sort(key=lambda x: x[2])
    print(f"  {label} losses ({len(losses)}):")
    for seed, seat, m, n_poor, reg in losses:
        print(f"    seed={seed} seat={seat} margin={m:,.0f} "
              f"poor_wool_days={n_poor} {reg}")
    close = [x for x in losses if x[2] >= -1000]
    print(f"  close losses (margin in [-1000, 0)): {len(close)}")


def print_gate():
    print("E70 PROMOTION GATE (locked before new episodes)\n")
    print("PROMOTE H4 only if ALL of:")
    print("  1. OOS seeds 32-63 both seats: H4 wins > losses and P(win) >= 0.60")
    print("  2. Combined E50+OOS: P(win) >= 0.70")
    print("  3. OOS and combined H4 p10 >= 0.97 * P1-S p10")
    print("  4. No new bad statuses/errors on OOS or field")
    print("  5. Field seeds 100-107: H4 wins >= losses vs every E51 family,")
    print("     and H4 total field wins >= P1-S total field wins (non-inferior)")
    print("H4 is allowed to keep known long wool-crash losses.")
    print("H4 vs H1 does not veto.\n")


def oos_ok(h4, p1s):
    return (h4["wins"] > h4["losses"] and h4["rate"] >= 0.60
            and h4["p10"] >= p1s["p10"] * 0.97
            and h4["bad"] == 0 and p1s["bad"] == 0
            and h4["errors"] == 0)


def combined_ok(h4, p1s):
    return h4["rate"] >= 0.70 and h4["p10"] >= p1s["p10"] * 0.97


def field_ok(h4_by_family, p1s_by_family):
    per_family = all(s["wins"] >= s["losses"] and s["bad"] == 0
                     for s in h4_by_family.values())
    h4_wins = sum(s["wins"] for s in h4_by_family.values())
    p1s_wins = sum(s["wins"] for s in p1s_by_family.values())
    p1s_clean = all(s["bad"] == 0 for s in p1s_by_family.values())
    return per_family and p1s_clean and h4_wins >= p1s_wins


def isolation():
    print("======== isolation ========")
    p1s, h4 = Config(**P1S), Config(**H4)
    assert p1s.harvest_defer_enabled is False
    assert p1s.endgame_rescue_feed is False
    assert h4.harvest_defer_enabled is True
    assert h4.harvest_defer_wool_only is True
    assert h4.endgame_rescue_feed is True
    assert h4.plant_latest_hour == -1
    assert h4.extra_crop == ""
    assert h4.hands_per_day == 6
    a = {k: getattr(p1s, k) for k in vars(Config)
         if not k.startswith("_") and not callable(getattr(Config, k))}
    b = {k: getattr(h4, k) for k in a}
    diff = {k for k in a if a[k] != b[k]}
    print(f"  P1-S vs H4 field diff: {sorted(diff)}")
    assert diff == {"harvest_defer_enabled", "harvest_defer_wool_only",
                    "endgame_rescue_feed"}
    print("  isolation OK\n")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def packet():
    print_gate()
    isolation()
    h4, p1s, recs, _ = run_pair("H4", H4, "P1S", P1S, OOS_SEEDS, "e70-h4-p1s-oos")
    oos = oos_ok(h4, p1s)
    print(f"\nOOS gate: {oos}  {h4['wins']}-{h4['losses']}-{h4['ties']} "
          f"P(win)={h4['rate']:.3f} p10 {h4['p10']:.0f} vs {p1s['p10']:.0f}")

    print("\n======== combine E50 + OOS ========")
    e50 = load_json(E50_PATH)
    combined = e50 + recs
    hdr = (f"{'matchup':<22}{'n':>4}{'w':>5}{'l':>5}{'t':>5}{'rate':>7}"
           f"{'money':>9}{'median':>9}{'p10':>8}{'p25':>8}{'p90':>8}")
    print(hdr)
    print("-" * len(hdr))
    c_h4 = summarize("H4 combined", combined, "H4")
    c_p = summarize("P1S combined", combined, "P1S")
    dump_losses(combined, "H4")
    regimes = dump_regimes(combined, "H4")
    comb = combined_ok(c_h4, c_p)
    print(f"combined gate: {comb}  {c_h4['wins']}-{c_h4['losses']}-{c_h4['ties']} "
          f"P(win)={c_h4['rate']:.3f}")

    print("\n======== field seeds 100-107 ========")
    h4_field = {}
    p1s_field = {}
    field_bad = 0
    for label, params in FIELD.items():
        cand, opp, _, _ = run_pair("H4", H4, label, params, FIELD_SEEDS,
                                   f"e70-h4-{label}")
        h4_field[label] = cand
        field_bad += cand["bad"] + opp["bad"]
        print()
    for label, params in FIELD.items():
        cand, opp, _, _ = run_pair("P1S", P1S, label, params, FIELD_SEEDS,
                                   f"e70-p1s-{label}")
        p1s_field[label] = cand
        field_bad += cand["bad"] + opp["bad"]
        print()
    fld = field_ok(h4_field, p1s_field) and field_bad == 0
    h4_field_wins = sum(s["wins"] for s in h4_field.values())
    p1s_field_wins = sum(s["wins"] for s in p1s_field.values())
    print(f"field gate: {fld}  H4 field wins={h4_field_wins} "
          f"P1-S field wins={p1s_field_wins}")

    print("\n======== optional H4 vs H1 seeds 200-207 ========")
    h4h1, h1h4, _, _ = run_pair("H4", H4, "H1", H1, H1_SEEDS, "e70-h4-h1")
    print(f"H4 vs H1 (informative): {h4h1['wins']}-{h4h1['losses']}-{h4h1['ties']} "
          f"P(win)={h4h1['rate']:.3f}")

    promote = oos and comb and fld
    decision = {
        "promote": promote,
        "oos_ok": oos,
        "combined_ok": comb,
        "field_ok": fld,
        "oos": {"H4": h4, "P1S": p1s},
        "combined": {"H4" : c_h4, "P1S": c_p, "regimes": regimes},
        "field": {"H4": h4_field, "P1S": p1s_field,
                  "H4_wins": h4_field_wins, "P1S_wins": p1s_field_wins},
        "h4_vs_h1": {"H4": h4h1, "H1": h1h4},
    }
    out = os.path.join(ROOT, "results", "e70-promotion-decision.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2)
    print(f"\n======== DECISION ========")
    print(f"  OOS={oos} combined={comb} field={fld}")
    print("PROMOTION:", "YES" if promote else "NO")
    print(f"decision json: {out}")
    return promote


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "packet"
    if stage == "gate":
        print_gate()
        isolation()
        return
    if stage == "packet":
        packet()
        return
    raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
