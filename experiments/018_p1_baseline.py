"""E18 - lock P1 as the Phase-5 baseline by reproducing E14.

Runs the same P1 vs P0 pairing on range(32), both seats, and diffs money and
winners against results/e14-finals-20260822-205557.json. P1 behaviour is not
changed; a mismatch means the baseline is not the E14 agent.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402

SEEDS = range(32)
E14_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "results", "e14-finals-20260822-205557.json")


def key(rec):
    return (rec["seed"], tuple(rec["agents"]))


def main():
    with open(E14_PATH, encoding="utf-8") as f:
        prior = {key(r): r for r in json.load(f)}

    jobs = H.build_jobs(H.spec("P1", **B.P1), H.spec("P0", **B.P0),
                        SEEDS, both_orders=True)
    t0 = time.perf_counter()

    def progress(rec, i, total):
        if i % 8 == 0 or i == total:
            print(f"  {i}/{total} episodes  ({time.perf_counter() - t0:.0f}s)",
                  flush=True)

    print(f"E18 baseline: P1 vs P0, {len(SEEDS)} seeds x 2 seats = {len(jobs)}\n",
          flush=True)
    records = H.run_jobs(jobs, progress=progress)
    base = H.save(records, "e18-baseline")

    mismatches = []
    for rec in records:
        old = prior.get(key(rec))
        if old is None:
            mismatches.append((key(rec), "missing from E14"))
            continue
        if rec["money"] != old["money"] or rec["winner"] != old["winner"]:
            mismatches.append((key(rec), rec["money"], rec["winner"],
                               old["money"], old["winner"]))

    print(f"\ncompared {len(records)} episodes to E14 finals")
    print(f"mismatches: {len(mismatches)}")
    for row in mismatches[:12]:
        print(f"  {row}")
    print(f"raw records: {base}.json")
    if mismatches:
        raise SystemExit("E18 FAILED: P1/P0 did not reproduce E14")
    print("E18 PASSED: P1 vs P0 reproduces E14 money and winners exactly.")


if __name__ == "__main__":
    main()
