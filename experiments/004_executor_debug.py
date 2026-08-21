"""Per-day trace of the v0 executor, to find where the turn budget actually goes.

Runs a short episode against a passive opponent and prints, for each day, what
the executor saw, what it decided, and what it lost.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import harness as H  # noqa: E402
from kagg.actions import OK, check_unit_action  # noqa: E402
from kagg.agent import Executor, World  # noqa: E402
from kagg.config import Config  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 8


class Traced(Executor):
    """Executor that keeps a per-day log of tasks, actions and rejections."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.log = {}

    def _plan(self, obs, configuration):
        w = World(obs, configuration)
        day = self.log.setdefault(w.day, {
            "tasks": Counter(), "ops": Counter(), "rejected": Counter(),
            "units": 0, "turns": 0, "money_start": w.money,
            "shed_start": dict((k, v) for k, v in w.shed.items() if v),
        })
        tasks = self._tasks(w)
        for t in tasks:
            day["tasks"][t.action[0]] += 1
        day["units"] += w.n_units
        day["turns"] += 1
        day["money_end"] = w.money
        day["shed_end"] = {k: v for k, v in w.shed.items() if v}
        day["seeds"] = {k: v for k, v in w.seeds.items() if v}
        day["hands"] = w.n_units - 1

        action = super()._plan(obs, configuration)
        # Re-derive what the planner wanted before validation clipped it.
        assignment = self._assign(w, self._tasks(w), float("inf"))
        raw = [self._action_for(w, i, assignment.get(i)) for i in range(w.n_units)]
        for idx, act in enumerate(raw):
            reason = check_unit_action(act, w.farm, w.private, idx, w.day,
                                       w.board, w.shed_capacity, ())
            if reason == OK:
                day["ops"][act[0]] += 1
            elif reason == "pass":
                day["ops"]["PASS"] += 1
            else:
                day["rejected"][f"{act[0]}:{reason}"] += 1
        day["market"] = Counter(o[0] for o in action["market"]) + day.get("market", Counter())
        return action


def main():
    cfg = Config(geese=4, crops=("WHEAT",), hands_per_day=6)
    traced = Traced(cfg)
    rec = H.play(("v0", traced), "pass", seed=1, episode_steps=DAYS * 24)

    print(f"v0 vs pass, {DAYS} days -> money={rec['money']} failure={rec['failure']}\n")
    for day in sorted(traced.log):
        d = traced.log[day]
        print(f"day {day:>2}  hands={d['hands']}  money {d['money_start']:>7.0f} -> "
              f"{d['money_end']:>7.0f}  unit-turns={d['units']}")
        print(f"        tasks/turn  {dict(d['tasks'].most_common(6))}")
        print(f"        actions     {dict(d['ops'].most_common(8))}")
        if d["rejected"]:
            print(f"        REJECTED    {dict(d['rejected'].most_common(6))}")
        print(f"        market      {dict(d['market'])}")
        print(f"        shed        {d['shed_end']}   seeds {d['seeds']}")

    p = rec["players"][0]
    print("\nsummary:")
    for key in ("categories", "harvested", "fertilizer_collected", "drought_deaths",
                "decay_deaths", "animals_escaped", "unsold_units", "hires"):
        print(f"  {key:<22} {p[key]}")


if __name__ == "__main__":
    main()
