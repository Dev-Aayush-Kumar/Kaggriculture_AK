"""Real-engine episode runner, instrumentation and aggregation.

The real engine is the only source of truth, so this module never simulates
anything: it wraps each agent in a probe that watches the (observation, action)
pairs flowing past and derives every metric from them.

Typical use:

    from harness import play, run_matchup, aggregate, report
    recs = run_matchup(("greedy", greedy), ("starter", "starter"), seeds=range(8))
    print(report(aggregate(recs, "greedy")))
"""

import contextlib
import csv
import inspect
import io
import json
import math
import multiprocessing
import os
import statistics
import sys
import time
from collections import Counter, namedtuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if os.path.join(_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))

# Importing kaggle_environments registers every bundled env, including open_spiel
# games that print several hundred lines to stderr. Swallow that once, here.
with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make as _make
    from kaggle_environments.envs.kaggriculture import kaggriculture as engine

from kagg import actions as A  # noqa: E402
from kagg.agent import Executor  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.market import PRICE_FLOOR, price, sell_revenue  # noqa: E402

RESULTS_DIR = os.path.join(_ROOT, "results")

BUILTIN = dict(engine.agents)


def quote_sale(item, qty, inventory):
    """Single-seller revenue and $1-floor units at this inventory.

    Uses the Phase-1 price curve. Units quoted at PRICE_FLOOR do not add
    supply, matching `sell_revenue`.
    """
    rev, _ = sell_revenue(item, qty, inventory)
    floor, inv = 0, inventory
    for _ in range(qty):
        p = price(item, inv)
        if p <= PRICE_FLOOR:
            floor += 1
        if p > PRICE_FLOOR:
            inv += 1
    return rev, floor

# ------------------------------------------------------------ agent registry
# Worker processes rebuild agents from a Spec rather than receiving a closure,
# because closures are not picklable and Windows uses spawn.

Spec = namedtuple("Spec", "label factory params")

FACTORIES = {
    "executor": lambda **params: Executor(Config(**params)),
}


def spec(label, factory="executor", **params):
    return Spec(label, factory, params)


def builtin(name):
    return Spec(name, None, {})


# --------------------------------------------------------------------- probing

def _tile_snapshot(tile):
    """Compact, comparable summary of one tile."""
    if tile is None:
        return ("EMPTY",)
    if tile == "LOCKED":
        return ("LOCKED",)
    if not isinstance(tile, dict):
        return ("?",)
    kind = tile.get("kind")
    if kind == "PLANT":
        return ("PLANT", tile["crop"], tile["planted_day"], tile["yield_units"],
                tile["max_lifespan_step"])
    if "animal" in tile:
        return ("ANIMAL", tile["animal"], tile["yield_units"])
    return (kind,)


class Probe:
    """Wraps an agent and accumulates every metric we can derive for free.

    Nothing here inspects engine internals; it only diffs successive
    observations and classifies the actions the agent asked for.
    """

    def __init__(self, name, fn, config):
        self.name = name
        self.fn = fn
        self.config = config
        self.wants_config = _arity(fn) >= 2
        self.turns_per_day = int(config.get("turnsPerDay", 24))
        self.board_size = int(config.get("boardSize", 10))
        self.shed_capacity = int(config.get("shedCapacity", 100))
        self.max_orders = int(config.get("maxMarketOrdersPerTurn", 10))

        self.latencies = []
        self.ops = Counter()
        self.cats = Counter()
        self.reasons = Counter()
        self.market_ops = Counter()
        self.sell_requested = Counter()
        self.sell_revenue = Counter()
        self.sell_floor_units = Counter()
        self.harvested = Counter()
        self.price_by_day = []
        self._animals = {}
        self.unit_turns = 0
        self.unit_actions_ok = 0
        self.travel = 0
        self.fertilizer_collected = 0
        self.dropped_orders = 0
        self.malformed_orders = 0
        self.hires = 0
        self.hands_turns = 0
        self.drought_deaths = 0
        self.decay_deaths = 0
        self.animals_escaped = 0
        self.decayed_units = 0
        self.shed_overflow = 0
        self.money_by_day = []
        self.errors = []
        self.turns = 0

        self._prev_tiles = None
        self._prev_step = -1
        self._hires_today = 0
        self._last_shed = {}
        self._last_seeds = {}
        self._min_overage = None
        self._worst_latency = (0.0, -1)

    # -- engine entry point -------------------------------------------------
    def make_callable(self):
        """A one-argument function, so the framework hands it only the obs."""
        def wrapped(observation):
            return self._act(observation)
        return wrapped

    def _act(self, obs):
        player = obs["player"]
        farm = obs["farms"][player]
        private = obs["private"]
        day, hour = obs["day"], obs["hour"]
        step = obs.get("step", day * self.turns_per_day + hour)

        self._diff_tiles(farm, step)
        self.turns += 1
        if hour == 0:
            self.money_by_day.append(round(farm["money"], 2))
            quotes = (obs.get("market") or {}).get("prices") or {}
            self.price_by_day.append({
                "MILK": quotes.get("MILK"),
                "WOOL": quotes.get("WOOL"),
                "EGG": quotes.get("EGG"),
            })
        animals = {}
        for row in farm["tiles"]:
            for tile in row:
                if isinstance(tile, dict) and "animal" in tile:
                    animals[tile["animal"]] = animals.get(tile["animal"], 0) + 1
        self._animals = animals
        overage = obs.get("remainingOverageTime")
        if overage is not None:
            self._min_overage = overage if self._min_overage is None else min(self._min_overage, overage)

        t0 = time.perf_counter()
        try:
            action = self.fn(obs, self.config) if self.wants_config else self.fn(obs)
        except Exception as exc:  # recorded, then re-raised so the seat gets ERROR
            self.latencies.append(time.perf_counter() - t0)
            self.errors.append(f"day{day}h{hour}: {type(exc).__name__}: {exc}")
            raise
        elapsed = time.perf_counter() - t0
        self.latencies.append(elapsed)
        if elapsed > self._worst_latency[0]:
            self._worst_latency = (elapsed, step)

        self._score_action(action, farm, private, day, obs.get("market") or {})

        self._last_shed = dict(private["shed"])
        self._last_seeds = dict(private["seeds"])
        # hires_today only grows within a day and is wiped at the boundary.
        if farm["hires_today"] < self._hires_today:
            self._hires_today = 0
        self.hires += max(0, farm["hires_today"] - self._hires_today)
        self._hires_today = farm["hires_today"]
        self.hands_turns += len(farm["hands"])

        if hour == self.turns_per_day - 1:
            carried = sum(sum(inv.values()) for inv in private["inventories"])
            excess = sum(private["shed"].values()) + carried - self.shed_capacity
            if excess > 0:
                self.shed_overflow += excess
        return action

    # -- accounting ---------------------------------------------------------
    def _diff_tiles(self, farm, step):
        snap = [[_tile_snapshot(t) for t in row] for row in farm["tiles"]]
        prev = self._prev_tiles
        if prev is not None:
            for y, row in enumerate(snap):
                for x, cur in enumerate(row):
                    old = prev[y][x]
                    if old[0] == "PLANT":
                        mls = old[4]
                        past_life = 0 <= mls <= self._prev_step
                        if cur[0] == "WEED":
                            if past_life:
                                self.decay_deaths += 1
                            else:
                                self.drought_deaths += 1
                        elif cur[0] == "PLANT" and cur[2] == old[2] and past_life:
                            self.decayed_units += max(0, old[3] - cur[3])
                    elif old[0] == "ANIMAL" and cur[0] in ("COOP", "PASTURE"):
                        self.animals_escaped += 1
        self._prev_tiles = snap
        self._prev_step = step

    def _score_action(self, action, farm, private, day, market=None):
        if not isinstance(action, dict):
            self.cats["wasted"] += 1
            self.reasons["action_not_a_dict"] += 1
            return
        farmer = action.get("farmer", ["PASS"])
        hands = action.get("hands", [])
        if not isinstance(hands, list):
            hands = []
        units = [farmer, *hands]
        blocked = A.blocked_plant_crops(units, private["seeds"])

        for idx, act in enumerate(units):
            if idx > 0 and idx - 1 >= len(farm["hands"]):
                self.reasons["action_for_missing_hand"] += 1
                continue
            self.unit_turns += 1
            op = act[0] if isinstance(act, (list, tuple)) and act else "?"
            self.ops[op] += 1
            reason = A.check_unit_action(
                act, farm, private, idx, day, self.board_size,
                self.shed_capacity, blocked)
            self.reasons[reason] += 1
            if reason == A.OK:
                self.unit_actions_ok += 1
                self.cats[A.category(act)] += 1
                if op in A.MOVES:
                    self.travel += 1
                elif op == "HARVEST":
                    pos = A.unit_position(farm, idx)
                    tile = farm["tiles"][pos[1]][pos[0]]
                    product = (tile["crop"] if tile.get("kind") == "PLANT"
                               else engine.ANIMALS[tile["animal"]]["product"])
                    self.harvested[product] += tile["yield_units"]
                elif op == "COLLECT_FERTILIZER":
                    self.fertilizer_collected += 1
            elif reason == "pass":
                self.cats["idle"] += 1
            else:
                self.cats["wasted"] += 1

        orders = action.get("market", [])
        if not isinstance(orders, list):
            self.reasons["market_not_a_list"] += 1
            return
        if len(orders) > self.max_orders:
            self.dropped_orders += len(orders) - self.max_orders
        for order in orders[:self.max_orders]:
            parsed = A.parse_market_order(order)
            if parsed is None:
                self.malformed_orders += 1
                continue
            self.market_ops[parsed["type"]] += 1
            if parsed["type"] == "SELL":
                item, qty = parsed["item"], parsed["remaining"]
                self.sell_requested[item] += qty
                # Quote-time walk of the existing price curve. Lockstep with the
                # other seat is not visible here, so this is the single-seller
                # estimate, not the engine's post-fill ledger.
                inv = ((market or {}).get("inventory") or {}).get(item)
                if inv is not None:
                    rev, floor = quote_sale(item, qty, inv)
                    self.sell_revenue[item] += rev
                    self.sell_floor_units[item] += floor

    # -- output -------------------------------------------------------------
    def stats(self):
        lat = sorted(self.latencies) or [0.0]
        return {
            "name": self.name,
            "turns": self.turns,
            "unit_turns": self.unit_turns,
            "hand_turns": self.hands_turns,
            "hires": self.hires,
            "effective_actions": self.unit_actions_ok,
            "effective_rate": _ratio(self.unit_actions_ok, self.unit_turns),
            "travel": self.travel,
            "categories": dict(self.cats),
            "category_share": {k: _ratio(v, self.unit_turns) for k, v in self.cats.items()},
            "ops": dict(self.ops),
            "top_waste": dict(Counter({k: v for k, v in self.reasons.items()
                                      if k not in (A.OK, "pass")}).most_common(8)),
            "harvested": dict(self.harvested),
            "harvested_units": sum(self.harvested.values()),
            "fertilizer_collected": self.fertilizer_collected,
            "market_ops": dict(self.market_ops),
            "sell_requested": dict(self.sell_requested),
            "sell_revenue": dict(self.sell_revenue),
            "sell_floor_units": dict(self.sell_floor_units),
            "price_by_day": self.price_by_day,
            "animals": dict(self._animals),
            "animal_count": sum(self._animals.values()),
            "dropped_orders": self.dropped_orders,
            "malformed_orders": self.malformed_orders,
            "drought_deaths": self.drought_deaths,
            "decay_deaths": self.decay_deaths,
            "decayed_units": self.decayed_units,
            "animals_escaped": self.animals_escaped,
            "shed_overflow": self.shed_overflow,
            "final_shed": {k: v for k, v in self._last_shed.items() if v},
            "unsold_units": sum(self._last_shed.values()),
            "unsold_seeds": sum(self._last_seeds.values()),
            "latency_mean_ms": round(1000 * sum(lat) / len(lat), 4),
            "latency_p50_ms": round(1000 * _pct(lat, 0.50), 4),
            "latency_p99_ms": round(1000 * _pct(lat, 0.99), 4),
            "latency_max_ms": round(1000 * lat[-1], 4),
            "latency_max_step": self._worst_latency[1],
            "min_overage_left": self._min_overage,
            "money_by_day": self.money_by_day,
            "errors": self.errors[:5],
            "n_errors": len(self.errors),
        }


# ------------------------------------------------------------------ episodes

def _arity(fn):
    target = fn.__call__ if not inspect.isfunction(fn) and hasattr(fn, "__call__") else fn
    try:
        params = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return 1
    return sum(1 for p in params.values()
               if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))


def resolve(agent):
    """Turn a Spec, a builtin name, a (label, callable) pair, or a bare callable
    into (label, callable). Only Specs and builtin names survive pickling."""
    if isinstance(agent, Spec):
        if agent.factory is None:
            return agent.label, BUILTIN[agent.label]
        return agent.label, FACTORIES[agent.factory](**agent.params)
    if isinstance(agent, str):
        return agent, BUILTIN[agent]
    if isinstance(agent, tuple) and len(agent) == 2:
        label, inner = agent
        return label, (BUILTIN[inner] if isinstance(inner, str) else inner)
    return getattr(agent, "__name__", agent.__class__.__name__), agent


def play(agent0, agent1, seed=0, episode_steps=720, config=None):
    """Run one episode and return a flat record. Never raises on agent failure."""
    name0, fn0 = resolve(agent0)
    name1, fn1 = resolve(agent1)
    cfg = {"episodeSteps": episode_steps, "seed": seed}
    if config:
        cfg.update(config)

    with contextlib.redirect_stderr(io.StringIO()):
        env = _make("kaggriculture", configuration=cfg, debug=False)
    probes = [Probe(name0, fn0, env.configuration), Probe(name1, fn1, env.configuration)]

    t0 = time.perf_counter()
    failure = None
    try:
        env.run([p.make_callable() for p in probes])
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - t0

    final = env.steps[-1]
    money = [float(final[i].observation.farms[i]["money"]) for i in range(2)]
    statuses = [final[i].status for i in range(2)]
    winner = None if money[0] == money[1] else (0 if money[0] > money[1] else 1)
    return {
        "seed": seed,
        "episode_steps": episode_steps,
        "turns_played": len(env.steps) - 1,
        "agents": [name0, name1],
        "money": money,
        "rewards": [final[i].reward for i in range(2)],
        "statuses": statuses,
        "winner": winner,
        "wall_seconds": round(wall, 3),
        "failure": failure,
        "players": [p.stats() for p in probes],
    }


def build_jobs(agent_a, agent_b, seeds, episode_steps=720, config=None,
               both_orders=True):
    """One job per (seed, seat order). Jobs are picklable when specs are used."""
    jobs = []
    for seed in seeds:
        for seat in ((0, 1) if both_orders else (0,)):
            pair = (agent_a, agent_b) if seat == 0 else (agent_b, agent_a)
            jobs.append((pair[0], pair[1], seed, episode_steps, config, seat))
    return jobs


def _run_job(job):
    a, b, seed, steps, config, seat = job
    rec = play(a, b, seed=seed, episode_steps=steps, config=config)
    rec["a_seat"] = seat
    return rec


def run_jobs(jobs, workers=None, progress=None):
    """Execute jobs, in parallel when the specs allow it.

    An episode costs ~13 s of pure framework overhead and the agents themselves
    take under a millisecond, so throughput is entirely a core count question.
    """
    picklable = all(isinstance(j[0], (Spec, str)) and isinstance(j[1], (Spec, str))
                    for j in jobs)
    if workers is None:
        workers = max(1, min(len(jobs), (os.cpu_count() or 2) - 1))
    if workers == 1 or not picklable or len(jobs) == 1:
        out = []
        for job in jobs:
            rec = _run_job(job)
            out.append(rec)
            if progress:
                progress(rec, len(out), len(jobs))
        return out

    out = []
    with multiprocessing.Pool(processes=workers) as pool:
        for rec in pool.imap_unordered(_run_job, jobs):
            out.append(rec)
            if progress:
                progress(rec, len(out), len(jobs))
    out.sort(key=lambda r: (r["seed"], r["a_seat"]))
    return out


def run_matchup(agent_a, agent_b, seeds, episode_steps=720, config=None,
                both_orders=True, workers=None, progress=None):
    """Play `agent_a` against `agent_b` on every seed, in both seat orders."""
    jobs = build_jobs(agent_a, agent_b, seeds, episode_steps, config, both_orders)
    return run_jobs(jobs, workers=workers, progress=progress)


# ----------------------------------------------------------------- reporting

def _ratio(a, b):
    return round(a / b, 4) if b else 0.0


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, max(0, int(math.ceil(q * len(sorted_vals))) - 1))
    return sorted_vals[k]


def aggregate(records, agent_name):
    """Summarise every seat in `records` occupied by `agent_name`."""
    money, opp_money, wins, losses, ties = [], [], 0, 0, 0
    walls, p99s, errors, timeouts = [], [], 0, 0
    unsold, deaths, escapes, overflow, dropped = [], [], [], [], []
    eff, travel_share = [], []
    cats = Counter()
    unit_turns = 0

    for rec in records:
        for seat in (0, 1):
            if rec["players"][seat]["name"] != agent_name:
                continue
            other = 1 - seat
            money.append(rec["money"][seat])
            opp_money.append(rec["money"][other])
            if rec["winner"] is None:
                ties += 1
            elif rec["winner"] == seat:
                wins += 1
            else:
                losses += 1
            p = rec["players"][seat]
            walls.append(rec["wall_seconds"])
            p99s.append(p["latency_p99_ms"])
            errors += p["n_errors"]
            timeouts += 1 if rec["statuses"][seat] in ("TIMEOUT", "ERROR") else 0
            unsold.append(p["unsold_units"])
            deaths.append(p["drought_deaths"])
            escapes.append(p["animals_escaped"])
            overflow.append(p["shed_overflow"])
            dropped.append(p["dropped_orders"])
            eff.append(p["effective_rate"])
            travel_share.append(p["category_share"].get("move", 0.0))
            for k, v in p["categories"].items():
                cats[k] += v
            unit_turns += p["unit_turns"]

    n = len(money)
    s = sorted(money)
    return {
        "agent": agent_name,
        "matches": n,
        "wins": wins, "losses": losses, "ties": ties,
        "win_rate": _ratio(wins, n),
        "mean_money": round(statistics.fmean(money), 1) if n else 0,
        "median_money": round(statistics.median(money), 1) if n else 0,
        "p10_money": round(_pct(s, 0.10), 1),
        "p90_money": round(_pct(s, 0.90), 1),
        "min_money": round(s[0], 1) if n else 0,
        "max_money": round(s[-1], 1) if n else 0,
        "mean_margin": round(statistics.fmean(
            [m - o for m, o in zip(money, opp_money)]), 1) if n else 0,
        "mean_wall_s": round(statistics.fmean(walls), 2) if n else 0,
        "p99_turn_ms": round(max(p99s), 3) if n else 0,
        "errors": errors,
        "bad_statuses": timeouts,
        "mean_unsold_units": round(statistics.fmean(unsold), 1) if n else 0,
        "mean_drought_deaths": round(statistics.fmean(deaths), 2) if n else 0,
        "mean_animals_escaped": round(statistics.fmean(escapes), 2) if n else 0,
        "mean_shed_overflow": round(statistics.fmean(overflow), 1) if n else 0,
        "mean_dropped_orders": round(statistics.fmean(dropped), 1) if n else 0,
        "mean_effective_rate": round(statistics.fmean(eff), 4) if n else 0,
        "mean_move_share": round(statistics.fmean(travel_share), 4) if n else 0,
        "action_budget": {k: _ratio(v, unit_turns) for k, v in cats.most_common()},
    }


_REPORT_ROWS = [
    ("matches", "matches", "{}"), ("wins", "wins", "{}"),
    ("losses", "losses", "{}"), ("ties", "ties", "{}"),
    ("win_rate", "win rate", "{:.3f}"),
    ("mean_money", "mean final money", "{:,.0f}"),
    ("median_money", "median final money", "{:,.0f}"),
    ("p10_money", "10th pct money", "{:,.0f}"),
    ("p90_money", "90th pct money", "{:,.0f}"),
    ("mean_margin", "mean margin vs opp", "{:+,.0f}"),
    ("mean_wall_s", "mean episode runtime s", "{:.2f}"),
    ("p99_turn_ms", "worst p99 turn ms", "{:.3f}"),
    ("mean_effective_rate", "effective action rate", "{:.3f}"),
    ("mean_move_share", "share of actions moving", "{:.3f}"),
    ("mean_unsold_units", "unsold units at end", "{:.1f}"),
    ("mean_drought_deaths", "plants lost to drought", "{:.2f}"),
    ("mean_animals_escaped", "animals escaped", "{:.2f}"),
    ("mean_shed_overflow", "shed overflow discarded", "{:.1f}"),
    ("mean_dropped_orders", "market orders dropped", "{:.1f}"),
    ("errors", "agent exceptions", "{}"),
    ("bad_statuses", "error/timeout seats", "{}"),
]


def report(summary):
    out = [f"=== {summary['agent']} ==="]
    for key, label, fmt in _REPORT_ROWS:
        out.append(f"  {label:<26} {fmt.format(summary[key])}")
    budget = summary["action_budget"]
    if budget:
        out.append("  action budget: " +
                   "  ".join(f"{k}={v:.1%}" for k, v in budget.items()))
    return "\n".join(out)


def save(records, tag):
    """Dump raw records as JSON and one summary row per seat as CSV."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.join(RESULTS_DIR, f"{tag}-{stamp}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1)
    rows = []
    for rec in records:
        for seat in (0, 1):
            p = rec["players"][seat]
            rows.append({
                "seed": rec["seed"], "seat": seat, "agent": p["name"],
                "opponent": rec["players"][1 - seat]["name"],
                "money": rec["money"][seat], "opp_money": rec["money"][1 - seat],
                "won": int(rec["winner"] == seat), "status": rec["statuses"][seat],
                "turns": rec["turns_played"], "wall_s": rec["wall_seconds"],
                "unit_turns": p["unit_turns"], "effective_rate": p["effective_rate"],
                "move_share": p["category_share"].get("move", 0.0),
                "harvested_units": p["harvested_units"],
                "milk_harvested": p.get("harvested", {}).get("MILK", 0),
                "wool_harvested": p.get("harvested", {}).get("WOOL", 0),
                "milk_revenue": p.get("sell_revenue", {}).get("MILK", 0),
                "wool_revenue": p.get("sell_revenue", {}).get("WOOL", 0),
                "milk_floor": p.get("sell_floor_units", {}).get("MILK", 0),
                "wool_floor": p.get("sell_floor_units", {}).get("WOOL", 0),
                "animal_count": p.get("animal_count", 0),
                "fertilizer_collected": p["fertilizer_collected"],
                "unsold_units": p["unsold_units"],
                "unsold_milk": p.get("final_shed", {}).get("MILK", 0),
                "unsold_wool": p.get("final_shed", {}).get("WOOL", 0),
                "drought_deaths": p["drought_deaths"],
                "animals_escaped": p["animals_escaped"],
                "shed_overflow": p["shed_overflow"],
                "latency_p99_ms": p["latency_p99_ms"],
                "n_errors": p["n_errors"],
            })
    with open(base + ".csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return base
