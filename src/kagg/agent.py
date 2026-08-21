"""The v0 executor: a deterministic, deadline-first farm operator.

It is not trying to be optimal. It is trying to be *correct and complete*, so
that strategy experiments measure the strategy rather than the plumbing:
nothing starves, nothing dries out, produce reaches the market, and every action
is validated before it leaves the building.

Structure of a turn:

    parse -> generate tasks from tile state -> assign tasks to units (routing
    policy) -> turn each assignment into one legal action -> plan market orders
    -> validate everything -> emit

Only the assignment step is pluggable; that is the variable E3 measures.
"""

import time

from .actions import (OK, blocked_plant_crops, check_unit_action,
                      is_shed_adjacent)
from .config import Config
from .econ.tables import (ANIMALS, CROPS, MARKET_PARAMS, PRODUCTS,
                          cumulative_hire_cost, shed_access_tiles)

# Task urgency. Lower runs first; anything that can be permanently lost today
# outranks anything that merely earns money.
P_FEED = 0
P_WATER = 1
P_RESCUE = 2        # yield about to be capped away or decayed away
P_CARE = 3
P_HARVEST_ANIMAL = 4
P_COLLECT = 5
P_HARVEST_CROP = 6
P_PLACE = 7
P_BUILD = 8
P_PLANT = 9
P_FERTILIZE = 10
P_DIG = 11

MAX_MARKET_ORDERS = 10


class Task:
    __slots__ = ("prio", "x", "y", "action", "item")

    def __init__(self, prio, x, y, action, item=None):
        self.prio, self.x, self.y, self.action, self.item = prio, x, y, action, item

    def __repr__(self):
        return f"Task({self.prio},{self.x},{self.y},{self.action})"


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class World:
    """Flat, typed view of one turn's observation."""

    def __init__(self, obs, config=None):
        cfg = config or {}
        self.player = obs["player"]
        self.farm = obs["farms"][self.player]
        self.private = obs["private"]
        self.tiles = self.farm["tiles"]
        self.board = len(self.tiles)
        self.day = obs["day"]
        self.hour = obs["hour"]
        self.turns_per_day = int(cfg.get("turnsPerDay", 24) or 24)
        self.episode_steps = int(cfg.get("episodeSteps", 720) or 720)
        self.shed_capacity = int(cfg.get("shedCapacity", 100) or 100)
        self.last_day = (self.episode_steps - 1) // self.turns_per_day
        self.money = self.farm["money"]
        self.shed = self.private["shed"]
        self.seeds = self.private["seeds"]
        self.inventories = self.private["inventories"]
        self.hands = self.farm["hands"]
        self.n_units = 1 + len(self.hands)
        self.units = [tuple(self.farm["farmer"])] + [tuple(h) for h in self.hands]
        self.prices = obs["market"]["prices"]
        self.access = shed_access_tiles(self.board)
        self.owned = [(x, y) for y, row in enumerate(self.tiles)
                      for x, t in enumerate(row) if t != "LOCKED"]
        self.layout_cache = None

    def inv(self, idx):
        return self.inventories[idx] if idx < len(self.inventories) else {}

    def tile(self, x, y):
        return self.tiles[y][x]

    def shed_used(self):
        return sum(self.shed.values())

    def nearest_access(self, pos):
        return min(self.access, key=lambda t: (manhattan(pos, t), t))

    def dist_to_shed(self, pos):
        return min(manhattan(pos, t) for t in self.access)


class Executor:
    """Callable agent. Instances are reused across turns within an episode."""

    def __init__(self, config=None):
        self.cfg = config or Config()

    # -- entry point --------------------------------------------------------
    def __call__(self, obs, configuration=None):
        n_hands = 0
        try:
            n_hands = len(obs["farms"][obs["player"]]["hands"])
        except Exception:
            pass
        try:
            return self._plan(obs, configuration)
        except Exception:
            # A crash must cost one turn, never the episode.
            return {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}

    def _plan(self, obs, configuration):
        deadline = time.perf_counter() + self.cfg.turn_budget_ms / 1000.0
        w = World(obs, configuration)
        orders = self._market_orders(w)
        tasks = self._tasks(w)
        assignment = self._assign(w, tasks, deadline)
        raw = self._actions(w, assignment, tasks)
        raw = self._finalize(w, raw)
        return {"farmer": raw[0], "hands": raw[1:], "market": orders[:MAX_MARKET_ORDERS]}

    # -- layout -------------------------------------------------------------
    def _layout(self, w):
        """Livestock takes the tiles nearest the shed; crops get the rest.

        A shed-access tile holding an animal is the cheapest square on the board:
        one unit standing there can draw feed, feed, care, harvest and collect
        fertilizer without ever moving.
        """
        if w.layout_cache is not None:
            return w.layout_cache
        cfg = self.cfg
        ordered = sorted(w.owned, key=lambda p: (w.dist_to_shed(p), p[1], p[0]))
        wanted = (["GOOSE"] * cfg.geese) + (["COW"] * cfg.cows) + (["SHEEP"] * cfg.sheep)
        slots = {}
        for animal, pos in zip(wanted, ordered):
            slots[pos] = animal
        # Never open more crop ground than the crew can water in a day. An
        # unwatered tile is not merely idle, it dies and leaves a weed behind.
        # Sized off the intended crew, not today's, so the field stays stable
        # on turns where the hands have not been hired yet.
        crew = max(1, cfg.hands_per_day + 1)
        limit = min(cfg.max_crop_tiles, int(crew * cfg.tiles_per_unit))
        crop_tiles = [p for p in ordered[len(slots):]][:limit]
        w.layout_cache = (slots, crop_tiles)
        return w.layout_cache

    # -- task generation ----------------------------------------------------
    def _tasks(self, w):
        """Only ever emit work the farm can actually finish.

        A task that cannot be completed is worse than no task: it still wins the
        priority contest, so it captures a unit and turns its whole day into
        PASS. Consumable-backed tasks are therefore issued against a running
        stock budget.
        """
        cfg = self.cfg
        slots, crop_tiles = self._layout(w)
        tasks = []
        stock = {}
        for item in ("WHEAT", "FERTILIZER", "GOOSE", "COW", "SHEEP"):
            stock[item] = w.shed.get(item, 0) + sum(
                w.inv(i).get(item, 0) for i in range(w.n_units))

        for (x, y), want in slots.items():
            tile = w.tile(x, y)
            structure = ANIMALS[want]["structure"]
            if tile is None:
                tasks.append(Task(P_BUILD, x, y, ["BUILD_" + structure]))
            elif not isinstance(tile, dict):
                continue
            elif tile.get("kind") == "WEED":
                tasks.append(Task(P_DIG, x, y, ["DIG"]))
            elif "animal" in tile:
                tasks.extend(self._animal_tasks(w, x, y, tile, stock))
            elif tile.get("kind") == structure:
                if stock.get(want, 0) > 0:
                    stock[want] -= 1
                    tasks.append(Task(P_PLACE, x, y, ["PLACE", want], want))
            elif tile.get("kind") in ("COOP", "PASTURE"):
                tasks.append(Task(P_DIG, x, y, ["DIG"]))   # wrong structure here

        seeds = dict(w.seeds)
        for i, (x, y) in enumerate(crop_tiles):
            tile = w.tile(x, y)
            if tile is None:
                crop = cfg.crops[i % len(cfg.crops)] if cfg.crops else None
                if crop and seeds.get(crop, 0) > 0 and self._can_mature(w, crop):
                    seeds[crop] -= 1
                    tasks.append(Task(P_PLANT, x, y, ["PLANT", crop]))
            elif not isinstance(tile, dict):
                continue
            elif tile.get("kind") == "WEED":
                tasks.append(Task(P_DIG, x, y, ["DIG"]))
            elif tile.get("kind") == "PLANT":
                tasks.extend(self._plant_tasks(w, x, y, tile, stock))
        return tasks

    def _animal_tasks(self, w, x, y, tile, stock):
        cfg = self.cfg
        out = []
        animal = ANIMALS[tile["animal"]]
        if not tile["fed_today"]:
            if stock.get("WHEAT", 0) > 0:
                stock["WHEAT"] -= 1
                out.append(Task(P_FEED, x, y, ["FEED"], "WHEAT"))
        elif cfg.care and not tile["cared_today"]:
            # CARE only banks a bonus on a day the animal was also fed, so it
            # waits until the feed has actually landed.
            out.append(Task(P_CARE, x, y, ["CARE"]))
        held = tile["yield_units"]
        if held > 0:
            full = held >= animal["max_held"]
            out.append(Task(P_RESCUE if full else P_HARVEST_ANIMAL, x, y, ["HARVEST"]))
        if cfg.collect_fertilizer and tile["fertilizer_available"]:
            out.append(Task(P_COLLECT, x, y, ["COLLECT_FERTILIZER"]))
        return out

    def _plant_tasks(self, w, x, y, tile, stock):
        cfg = self.cfg
        out = []
        crop = CROPS[tile["crop"]]
        age = w.day - tile["planted_day"]
        ripe = tile["yield_units"] > 0 and age >= crop["first_yield_day"]
        decaying = 0 <= tile["max_lifespan_step"] <= w.day * w.turns_per_day + w.hour
        endgame = w.day >= w.last_day
        spent = not crop["ongoing"] and age >= crop["max_yield_day"]

        if spent:
            # The plant can never be worth more than it is at the end of today,
            # and it starts rotting at midnight, so take the last watering bonus
            # and then lift it with the same urgency as a deadline.
            if not tile["watered_today"] and age == crop["max_yield_day"] and not decaying:
                out.append(Task(P_WATER, x, y, ["WATER"]))
            elif ripe:
                out.append(Task(P_RESCUE, x, y, ["HARVEST"]))
            return out

        if ripe and (decaying or endgame):
            out.append(Task(P_RESCUE, x, y, ["HARVEST"]))
        elif ripe and crop["ongoing"]:
            out.append(Task(P_HARVEST_CROP, x, y, ["HARVEST"]))
        if not tile["watered_today"]:
            out.append(Task(P_WATER, x, y, ["WATER"]))
        if (cfg.fertilize_crops and tile["fertilized_until_day"] < w.day
                and stock.get("FERTILIZER", 0) > 0):
            window = (crop["max_yield_day"] + 1) // 2
            if crop["ongoing"] or window <= age <= crop["max_yield_day"]:
                stock["FERTILIZER"] -= 1
                out.append(Task(P_FERTILIZE, x, y, ["FERTILIZE"], "FERTILIZER"))
        return out

    def _can_mature(self, w, crop):
        return w.day + CROPS[crop]["max_yield_day"] <= w.last_day

    # -- routing ------------------------------------------------------------
    def _assign(self, w, tasks, deadline):
        policy = self.cfg.routing
        if policy == "nearest":
            return self._assign_nearest(w, tasks, range(w.n_units), deadline)
        zones = self._zones(w)
        assignment = {}
        for idx in range(w.n_units):
            zone = zones[idx]
            mine = [t for t in tasks if (t.x, t.y) in zone]
            if not mine:
                continue
            if policy == "zone_nearest":
                pick = min(mine, key=lambda t: (t.prio, self._cost(w, idx, t), t.y, t.x))
            else:
                pick = min(mine, key=lambda t: (t.prio, t.y, t.x))
            assignment[idx] = pick
            tasks = [t for t in tasks if t is not pick]
        return assignment

    def _assign_nearest(self, w, tasks, unit_ids, deadline):
        """Greedy over (unit, task) pairs ordered by urgency then travel.

        Scoring pairs rather than tasks matters: a unit already standing on a
        tile costs nothing to use, so this keeps a unit that just watered a tile
        on the spot to harvest it instead of marching it across the farm.
        """
        units = list(unit_ids)
        pairs = []
        for task in tasks:
            for idx in units:
                pairs.append((task.prio, self._cost(w, idx, task), idx, task.y, task.x, task))
        pairs.sort(key=lambda p: p[:5])
        assignment = {}
        claimed = set()
        for _, _, idx, _, _, task in pairs:
            if len(assignment) >= len(units):
                break
            if idx in assignment or id(task) in claimed:
                continue
            if time.perf_counter() > deadline:
                break
            assignment[idx] = task
            claimed.add(id(task))
        return assignment

    def _cost(self, w, idx, task):
        """Turns to complete the task, including a shed detour if it needs an item."""
        pos = w.units[idx]
        if task.item and w.inv(idx).get(task.item, 0) < 1:
            depot = w.nearest_access(pos)
            return manhattan(pos, depot) + 1 + manhattan(depot, (task.x, task.y))
        return manhattan(pos, (task.x, task.y))

    def _zones(self, w):
        """Split owned tiles into contiguous vertical bands, one per unit."""
        ordered = sorted(w.owned)
        n = max(1, w.n_units)
        size = max(1, (len(ordered) + n - 1) // n)
        return [set(ordered[i * size:(i + 1) * size]) for i in range(n)]

    # -- action synthesis ---------------------------------------------------
    def _actions(self, w, assignment, tasks):
        """Turn assignments into actions, never leaving a unit idle by accident.

        If an assignment degenerates to PASS -- typically because the unit and
        the task disagree about who is carrying what -- the unit falls through
        to the best remaining unclaimed task instead of wasting the turn.
        """
        claimed = {id(t) for t in assignment.values()}
        spare = sorted((t for t in tasks if id(t) not in claimed),
                       key=lambda t: (t.prio, t.y, t.x))
        out = []
        for idx in range(w.n_units):
            act = self._action_for(w, idx, assignment.get(idx))
            if act == ["PASS"] and spare:
                for j, task in enumerate(spare):
                    alt = self._action_for(w, idx, task)
                    if alt != ["PASS"]:
                        act = alt
                        spare.pop(j)
                        break
            out.append(act)
        return out

    def _action_for(self, w, idx, task):
        pos = w.units[idx]
        inv = w.inv(idx)
        if task is None:
            return self._idle_action(w, idx, pos, inv)
        if task.item and inv.get(task.item, 0) < 1:
            depot = w.nearest_access(pos)
            if pos == depot or is_shed_adjacent(pos, w.board):
                qty = 1 if task.item in ANIMALS else self._feed_pickup_qty(w)
                if w.shed.get(task.item, 0) > 0:
                    return ["PICKUP", task.item, qty]
                return ["PASS"]
            return self._step_toward(pos, depot)
        if pos == (task.x, task.y):
            return list(task.action)
        return self._step_toward(pos, (task.x, task.y))

    def _feed_pickup_qty(self, w):
        n_animals = sum(1 for y, row in enumerate(w.tiles) for x, t in enumerate(row)
                        if isinstance(t, dict) and "animal" in t)
        return max(1, min(w.shed.get("WHEAT", 0), max(1, n_animals)))

    def _idle_action(self, w, idx, pos, inv):
        """Idle units run produce back to the shed so it can be sold today.

        Walking to the shed only pays for a worthwhile load; anything smaller
        rides along until the free end-of-day drop.
        """
        carried = sum(inv.values())
        if not carried:
            return ["PASS"]
        if is_shed_adjacent(pos, w.board):
            return ["DROP"]
        if carried >= self.cfg.drop_threshold or w.hour >= w.turns_per_day - 4:
            return self._step_toward(pos, w.nearest_access(pos))
        return ["PASS"]

    def _step_toward(self, pos, target):
        dx = target[0] - pos[0]
        dy = target[1] - pos[1]
        if dx:
            return ["EAST"] if dx > 0 else ["WEST"]
        if dy:
            return ["SOUTH"] if dy > 0 else ["NORTH"]
        return ["PASS"]

    # -- market -------------------------------------------------------------
    def _market_orders(self, w):
        cfg = self.cfg
        orders = []
        # The final day still has a full harvest and the liquidation on it, so
        # hire right through it.
        if w.hour == cfg.hire_hour and w.day <= w.last_day and cfg.hands_per_day > 0:
            n = min(cfg.hands_per_day, MAX_MARKET_ORDERS)
            if w.money - cumulative_hire_cost(n) >= cfg.hire_reserve:
                orders.extend([["HIRE"]] * n)

        n_animals = sum(1 for row in w.tiles for t in row
                        if isinstance(t, dict) and "animal" in t)
        feed_target = n_animals * cfg.feed_buffer
        orders.extend(self._sell_orders(w, feed_target))

        # Feed outranks every other purchase: two missed days and the animal is
        # gone along with the capital that bought it.
        wheat_short = feed_target - w.shed.get("WHEAT", 0)
        if n_animals and wheat_short > 0:
            room = w.shed_capacity - w.shed_used()
            qty = max(0, min(wheat_short, room))
            if qty:
                orders.append(["BUY_PRODUCT", "WHEAT", qty])

        orders.extend(self._acquisition_orders(w, n_animals))
        return orders

    def _sell_orders(self, w, feed_target):
        cfg = self.cfg
        liquidating = w.day >= cfg.liquidate_day
        out = []
        for item in PRODUCTS:
            qty = w.shed.get(item, 0)
            if item == "WHEAT" and not liquidating:
                qty -= feed_target
            if qty <= 0:
                continue
            base = MARKET_PARAMS[item]["base"]
            quote = w.prices.get(item, base)
            if liquidating or quote >= base * cfg.sell_floor_fraction:
                out.append(["SELL", item, qty])
        return out

    def _acquisition_orders(self, w, n_animals):
        cfg = self.cfg
        out = []
        slots, crop_tiles = self._layout(w)
        if w.day >= cfg.liquidate_day:
            return out

        for quadrant in cfg.buy_land:
            if quadrant not in w.farm["unlocked_quadrants"]:
                out.append(["BUY_LAND"])
                break

        wanted = {}
        for animal in slots.values():
            wanted[animal] = wanted.get(animal, 0) + 1
        for animal, n in sorted(wanted.items()):
            # Count animals in transit too. A goose being carried to its coop is
            # on no tile and in no shed, and forgetting it buys a second one.
            have = sum(1 for row in w.tiles for t in row
                       if isinstance(t, dict) and t.get("animal") == animal)
            have += w.shed.get(animal, 0)
            have += sum(w.inv(i).get(animal, 0) for i in range(w.n_units))
            short = n - have
            cost = ANIMALS[animal]["cost"]
            budget = w.money - cfg.livestock_reserve
            if short > 0 and budget >= cost and w.shed_used() < w.shed_capacity:
                out.append(["BUY_ANIMAL", animal, min(short, int(budget // cost))])

        if cfg.crops:
            empty = sum(1 for (x, y) in crop_tiles if w.tile(x, y) is None)
            for crop in cfg.crops:
                if not self._can_mature(w, crop):
                    continue
                share = -(-empty // len(cfg.crops))          # ceil
                need = min(share, cfg.seed_batch) - w.seeds.get(crop, 0)
                cost = CROPS[crop]["seed"]
                budget = w.money - cfg.seed_reserve
                if need > 0 and budget >= cost:
                    out.append(["BUY_SEED", crop, min(need, int(budget // cost))])
        return out

    # -- validation ---------------------------------------------------------
    def _finalize(self, w, raw):
        """Last gate: anything the engine would ignore becomes an explicit PASS.

        Also enforces the interpreter's atomic-PLANT rule, which drops *all*
        PLANT requests for a crop when they collectively outrun the seed count.
        """
        seeds = dict(w.seeds)
        out = []
        for act in raw:
            if isinstance(act, list) and len(act) >= 2 and act[0] == "PLANT":
                if seeds.get(act[1], 0) <= 0:
                    out.append(["PASS"])
                    continue
                seeds[act[1]] -= 1
            out.append(act)

        blocked = blocked_plant_crops(out, w.seeds)
        checked = []
        for idx, act in enumerate(out):
            reason = check_unit_action(act, w.farm, w.private, idx, w.day,
                                       w.board, w.shed_capacity, blocked)
            checked.append(act if reason == OK else ["PASS"])
        return checked


def build(**overrides):
    """Factory used by the research registry and by main.py."""
    return Executor(Config(**overrides))


agent = Executor()
