"""E69 - live drought/action forensics on frozen H4. No strategy change.

Replays E50 loss matchups (and seed 0 as a win control). For every plant
that becomes a weed before max lifespan, records planting hour, whether a
WATER task existed, and which action the zone unit actually took.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.agent import Executor, World  # noqa: E402
from kagg.config import Config  # noqa: E402

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)

# E50 H4-loss matchups: (seed, h4_seat)
LOSSES = [
    (2, 0), (18, 0), (22, 1), (23, 0), (24, 0), (29, 0), (29, 1),
]
CONTROL = [(0, 0)]


def plant_key(x, y, planted_day):
    return (x, y, planted_day)


class Forensic(Executor):
    """Executor that records unwatered plants and the action that beat WATER."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.prev = {}
        self.alive = {}
        self.deaths = []
        self.hour_notes = []
        self.ops = Counter()
        self.deferred_wool_hours = 0
        self.water_tasks = 0
        self.water_ops = 0

    def _scan(self, w):
        found = {}
        for y, row in enumerate(w.tiles):
            for x, t in enumerate(row):
                if not (isinstance(t, dict) and t.get("kind") == "PLANT"):
                    continue
                rec = {
                    "x": x, "y": y, "crop": t.get("crop"),
                    "planted_day": t.get("planted_day"),
                    "yield": t.get("yield_units"),
                    "watered": bool(t.get("watered_today")),
                    "unwatered": int(t.get("consecutive_unwatered", 0)),
                    "mls": t.get("max_lifespan_step", -1),
                }
                found[(x, y)] = rec
                key = plant_key(x, y, rec["planted_day"])
                if key not in self.alive:
                    self.alive[key] = {
                        "first_day": w.day, "first_hour": w.hour,
                        "crop": rec["crop"], "hours": [],
                    }
        return found

    def _note_deaths(self, w, found):
        for pos, old in self.prev.items():
            if pos in found:
                continue
            past_life = 0 <= (old.get("mls") or -1) <= (w.day * 24 + w.hour - 1)
            kind = "decay" if past_life else "drought"
            key = plant_key(old["x"], old["y"], old["planted_day"])
            hist = self.alive.pop(key, {"hours": [], "first_day": None,
                                        "first_hour": None, "crop": old["crop"]})
            self.deaths.append({
                "kind": kind, "day": w.day, "hour": w.hour,
                "x": old["x"], "y": old["y"], "crop": old["crop"],
                "planted_day": old["planted_day"],
                "first_day": hist.get("first_day"),
                "first_hour": hist.get("first_hour"),
                "yield": old.get("yield"),
                "unwatered": old.get("unwatered"),
                "hours": hist.get("hours") or [],
            })

    def _plan(self, obs, configuration):
        w = World(obs, configuration)
        found = self._scan(w)
        self._note_deaths(w, found)

        tasks = self._tasks(w)
        water_xy = {(t.x, t.y) for t in tasks if t.action and t.action[0] == "WATER"}
        self.water_tasks += len(water_xy)
        feed_xy = {(t.x, t.y) for t in tasks if t.action and t.action[0] == "FEED"}
        assignment = self._assign(w, tasks, float("inf"))
        assigned_xy = {}
        for idx, task in assignment.items():
            assigned_xy[(task.x, task.y)] = (idx, task.action[0], task.prio)

        action = super()._plan(obs, configuration)
        units = [action.get("farmer", ["PASS"])]
        units.extend(action.get("hands") or [])
        for act in units:
            op = act[0] if act else "PASS"
            self.ops[op] += 1
            if op == "WATER":
                self.water_ops += 1

        unit_ops = []
        for idx, act in enumerate(units):
            pos = w.units[idx] if idx < len(w.units) else None
            unit_ops.append({
                "idx": idx, "pos": pos,
                "op": act[0] if act else "PASS",
                "assigned": (assignment[idx].action[0] if idx in assignment else None),
                "task_xy": ((assignment[idx].x, assignment[idx].y)
                            if idx in assignment else None),
            })

        for pos, rec in found.items():
            if rec["watered"]:
                continue
            key = plant_key(rec["x"], rec["y"], rec["planted_day"])
            nearest = None
            ndist = 99
            nop = None
            for u in unit_ops:
                if not u["pos"]:
                    continue
                d = abs(u["pos"][0] - rec["x"]) + abs(u["pos"][1] - rec["y"])
                if d < ndist:
                    ndist, nearest, nop = d, u["idx"], u["op"]
            note = {
                "day": w.day, "hour": w.hour, "x": rec["x"], "y": rec["y"],
                "unwatered": rec["unwatered"],
                "water_task": pos in water_xy,
                "assigned": assigned_xy.get(pos),
                "nearest": nearest, "ndist": ndist, "nop": nop,
                "n_feed_tasks": len(feed_xy),
                "n_units": w.n_units,
            }
            if key in self.alive:
                hours = self.alive[key]["hours"]
                hours.append(note)
                if len(hours) > 28:
                    del hours[:-28]
            # wool defer hours: animal harvest skipped while plant needs water
            if pos in water_xy and assigned_xy.get(pos) is None:
                self.hour_notes.append(note)

        self.prev = found
        return action


def cause_of(death):
    """One-line cause from the plant's last hours. UNKNOWN if unclear."""
    hours = death.get("hours") or []
    if not hours:
        return "UNKNOWN no-hour-log"
    plant_day = [h for h in hours if h["day"] == death.get("planted_day")]
    src = plant_day or hours
    water_task_n = sum(1 for h in src if h["water_task"])
    assigned_n = sum(1 for h in src if h["assigned"])
    last = src[-1]
    ops = Counter(h["nop"] for h in src)
    if last["ndist"] == 0 and last["nop"] != "WATER":
        return (f"on-tile {last['nop']} beat WATER "
                f"d{last['day']}h{last['hour']} (ops {dict(ops)})")
    if water_task_n == 0:
        return f"no WATER task emitted in {len(src)} unwatered hours ops={dict(ops)}"
    if assigned_n == 0:
        return (f"WATER task existed but never assigned "
                f"nearest={last['nop']} dist={last['ndist']} "
                f"feed_tasks={last['n_feed_tasks']} ops={dict(ops)}")
    walked = sum(1 for h in src if h["nop"] in ("NORTH", "SOUTH", "EAST", "WEST"))
    if walked and last["nop"] != "WATER":
        return (f"assigned WATER but walking/other last={last['nop']} "
                f"dist={last['ndist']} walked={walked}/{len(src)}")
    return f"UNKNOWN last={last} ops={dict(ops)}"


def run_one(seed, h4_seat, tag):
    h4 = Forensic(Config(**H4))
    p1 = Executor(Config(**dict(B.P1_S)))
    if h4_seat == 0:
        rec = H.play(("H4", h4), ("P1S", p1), seed=seed)
    else:
        rec = H.play(("P1S", p1), ("H4", h4), seed=seed)
    droughts = [d for d in h4.deaths if d["kind"] == "drought"]
    decays = [d for d in h4.deaths if d["kind"] == "decay"]
    print(f"\n=== {tag} seed {seed} H4 seat {h4_seat}  "
          f"money {rec['money']} winner={rec['winner']} ===")
    print(f"  probe drought={rec['players'][h4_seat].get('drought_deaths')} "
          f"traced drought={len(droughts)} decay={len(decays)}")
    print(f"  ops water {h4.water_ops}/{h4.water_tasks} tasks  "
          f"FEED={h4.ops.get('FEED', 0)} HARVEST={h4.ops.get('HARVEST', 0)} "
          f"CARE={h4.ops.get('CARE', 0)} PASS={h4.ops.get('PASS', 0)}")
    causes = Counter()
    for d in droughts:
        c = cause_of(d)
        causes[c.split(" beat ")[0][:40] if " beat " in c else c[:50]] += 1
        print(f"  DROUGHT {d['crop']} @({d['x']},{d['y']}) planted d{d['planted_day']} "
              f"first={d['first_day']}h{d['first_hour']} died obs d{d['day']}h{d['hour']} "
              f"unwatered={d['unwatered']} yield={d['yield']}")
        print(f"    CAUSE {c}")
        last = (d["hours"] or [None])[-1]
        if last:
            print(f"    last h{last['hour']} water_task={last['water_task']} "
                  f"assigned={last['assigned']} nearest_u{last['nearest']} "
                  f"{last['nop']} dist={last['ndist']} feed_tasks={last['n_feed_tasks']}")
    return droughts, causes, rec


def main():
    print("E69 Phase 17 live drought forensics\n")
    all_causes = Counter()
    n_d = 0
    print("---- E50 loss matchups ----")
    for seed, seat in LOSSES:
        droughts, causes, _ = run_one(seed, seat, "LOSS")
        all_causes.update(causes)
        n_d += len(droughts)
    print("\n---- seed 0 win-control ----")
    droughts, causes, _ = run_one(0, 0, "CTRL")
    all_causes.update(causes)
    n_d += len(droughts)
    print(f"\n======== cause totals across {n_d} droughts ========")
    for k, v in all_causes.most_common():
        print(f"  {v:3}  {k}")


if __name__ == "__main__":
    main()
