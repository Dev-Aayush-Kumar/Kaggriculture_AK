"""E52 - pin P1-S / H1 / H3 / H4 isolation. No behaviour change.

One paired seed of H4 vs P1-S is enough to confirm H4 still runs and
still leaves the leftover late escape that E53 diagnoses.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.config import Config  # noqa: E402

H1 = dict(B.P1_S, harvest_defer_enabled=True)
H3 = dict(H1, harvest_defer_wool_only=True)
H4 = dict(H3, endgame_rescue_feed=True)


def flags(params):
    cfg = Config(**params)
    return {
        "harvest_defer_enabled": cfg.harvest_defer_enabled,
        "harvest_defer_hold_full": cfg.harvest_defer_hold_full,
        "harvest_defer_wool_only": cfg.harvest_defer_wool_only,
        "endgame_rescue_feed": cfg.endgame_rescue_feed,
        "sell_defer_enabled": cfg.sell_defer_enabled,
        "sale_qty_enabled": cfg.sale_qty_enabled,
        "cows": cfg.cows, "sheep": cfg.sheep, "routing": cfg.routing,
    }


def main():
    print("E52 baseline verification\n")
    for name, params in (("P1-S", B.P1_S), ("H1", H1), ("H3", H3), ("H4", H4)):
        print(f"  {name}: {flags(params)}")
    assert Config().endgame_rescue_feed is False
    assert Config(**B.P1_S).endgame_rescue_feed is False
    assert Config(**H4).endgame_rescue_feed is True
    print("\nconfig isolation: ok")

    jobs = H.build_jobs(H.spec("H4", **H4), H.spec("P1S", **dict(B.P1_S)),
                        range(1), both_orders=True)
    print(f"\nH4 vs P1-S, 1 seed x 2 = {len(jobs)}", flush=True)
    records = H.run_jobs(jobs)
    for rec in records:
        for seat in (0, 1):
            p = rec["players"][seat]
            late = [ev for ev in p.get("escape_events") or []
                    if ev.get("loss_day", -1) >= 28 or ev.get("obs_day", -1) >= 29]
            print(f"  seed {rec['seed']} seat {seat} {p['name']} "
                  f"money={rec['money'][seat]} escaped={p['animals_escaped']} "
                  f"late={len(late)} "
                  f"{[(ev.get('animal'), ev.get('x'), ev.get('y'), ev.get('loss_day')) for ev in late]}")
    print(f"raw: {H.save(records, 'e52-h4-p1s')}.json")


if __name__ == "__main__":
    main()
