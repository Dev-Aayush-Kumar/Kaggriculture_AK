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
from .econ.market import (buy_cost, expected_remaining_demand, marginal_value,
                          units_until_price)
from .econ.opportunity import (evaluate_opportunities, select_opportunity,
                                snapshot_from_obs)
from .econ.momentum import decide_stay_or_convert
from .econ.tables import (ANIMALS, CROPS, LAND_PRICES, MARKET_I0, MARKET_PARAMS,
                          PRODUCTS, cumulative_hire_cost, quadrant_of,
                          shed_access_tiles)

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


def shed_trip_justified(carried_count, carried_value, distance, hour, turns_per_day,
                        drop_threshold, move_ev_enabled, min_trip_value_per_step):
    """Whether an idle unit should walk a load to the shed.

    The default (flag off) is the original count threshold. The EV rule only
    changes idle logistics; assigned feed/water/rescue walks are untouched.
    Late-day walks stay mandatory so stock is not left in hand overnight.
    """
    if carried_count <= 0:
        return False
    if hour >= turns_per_day - 4:
        return True
    if not move_ev_enabled:
        return carried_count >= drop_threshold
    return carried_value >= min_trip_value_per_step * max(1, distance)


def sale_justified(quote, base, day, last_day, shed_used, shed_capacity,
                   sell_floor_fraction, liquidating, sell_defer_enabled,
                   sell_defer_force_days, sell_defer_shed_frac):
    """Whether a produce lot should be sold this turn.

    Flag off is the original rule: sell if liquidating or the quote clears the
    floor. Flag on applies that floor even inside the liquidation window,
    unless remaining days are at or below sell_defer_force_days (negative
    means never time-force) or the shed is approaching capacity.
    """
    above_floor = quote >= base * sell_floor_fraction
    if not sell_defer_enabled:
        return liquidating or above_floor
    if above_floor:
        return True
    if last_day - day <= sell_defer_force_days:
        return True
    if shed_capacity > 0 and shed_used >= sell_defer_shed_frac * shed_capacity:
        return True
    return False


def harvest_deferred(quote, base, held, max_held, harvest_defer_enabled,
                     harvest_defer_floor_fraction, hold_full=False,
                     day=0, last_day=29, force_days=0, product=None,
                     wool_only=False, harvest_defer_force_days=-1):
    """Whether animal yield should stay on the tile instead of going to the shed.

    Flag off never defers. Flag on holds a non-full load while the quote is
    below the existing sell-floor fraction, so a poor market does not fill
    the shed and force a dump. A full tile is still harvested unless
    hold_full is on, in which case it also waits for a good quote or the
    existing last-day force. wool_only leaves milk (and eggs) on the
    original always-lift rule. harvest_defer_force_days >= 0 lifts once
    remaining days are at or below that value (H4 passes -1).
    """
    if not harvest_defer_enabled or held <= 0:
        return False
    if harvest_defer_force_days >= 0 and last_day - day <= harvest_defer_force_days:
        return False
    if wool_only and product != "WOOL":
        return False
    if quote >= base * harvest_defer_floor_fraction:
        return False
    if held < max_held:
        return True
    if not hold_full:
        return False
    return last_day - day > force_days


def capped_sale_qty(qty, item, inventory, sale_qty_floor, sale_qty_enabled,
                    day, last_day, shed_used, shed_capacity,
                    sale_qty_force_days, sale_qty_shed_frac):
    """How many units of `item` to sell this turn.

    Flag off returns the whole lot. Flag on walks the existing price curve
    only as far as sale_qty_floor, except on a hard-loss turn (last days or
    a nearly full shed) when leftover stock would be worse than a cheap sale.
    """
    if qty <= 0:
        return 0
    forced = (last_day - day <= sale_qty_force_days) or (
        shed_capacity > 0 and shed_used >= sale_qty_shed_frac * shed_capacity)
    if not sale_qty_enabled or forced or inventory is None:
        return qty
    return min(qty, units_until_price(item, inventory, sale_qty_floor))


def rescue_feed_action(enabled, day, last_day, fed_today, consecutive_unfed,
                       wheat_in_hand, remain_value, wheat_base=None):
    """Whether a unit already on an at-risk animal should feed it tonight.

    E46/E47: every late escape was end of day 28, consecutive_unfed=1,
    wheat still in the shed, and the crew often harvested that same tile
    without feeding. Remaining production is one event. Rescue only when
    that event's quote exceeds the wheat base (class C) and the unit is
    already carrying wheat — one action, no chase, no second planner.

    Returns "FEED" or None. Flag off is always None.
    """
    if wheat_base is None:
        wheat_base = MARKET_PARAMS["WHEAT"]["base"]
    if not enabled:
        return None
    if day != last_day - 1:
        return None
    if fed_today or consecutive_unfed < 1:
        return None
    if remain_value is None or remain_value <= wheat_base:
        return None
    if wheat_in_hand >= 1:
        return "FEED"
    return None


def wheat_feed_short(shed_wheat, carried_wheat, n_animals, feed_buffer,
                     count_carried=False):
    """How many wheat the market should buy to refill the feed buffer.

    Flag off is the original shed-only check. Flag on includes wheat already
    in unit inventories so a pickup does not look like a shortage.
    """
    target = n_animals * feed_buffer
    held = shed_wheat + (carried_wheat if count_carried else 0)
    return max(0, target - held)


def feed_pickup_qty(shed_wheat, n_animals, feed_pickup_cap=0):
    """How many wheat a unit should PICKUP for a FEED task.

    Cap 0 is the original rule: take min(shed, n_animals), at least 1.
    Cap > 0 limits that draw so one trip cannot empty the day's buffer.
    """
    want = max(1, n_animals)
    if feed_pickup_cap > 0:
        want = min(want, feed_pickup_cap)
    return max(1, min(max(0, shed_wheat), want))


def plant_hour_allowed(hour, plant_latest_hour):
    """Whether a PLANT task may be issued this hour.

    Flag off (<0) never blocks. Flag on refuses planting after
    plant_latest_hour so the same day still has a turn left to WATER:
    the engine starts consecutive_unwatered at 1 on the planting day,
    and two unwatered days turn the tile into a weed.
    """
    if plant_latest_hour < 0:
        return True
    return hour <= plant_latest_hour


def remaining_yield_events(animal, placed_day, from_day, last_day):
    """How many production events `animal` still has if placed on `placed_day`.

    Mirrors the engine's end-of-day test:
    `days_since_first = (day + 1) - placed_day - first_yield_day`.
    """
    spec = ANIMALS[animal]
    first, interval = spec["first_yield_day"], spec["interval"]
    n = 0
    for day in range(from_day, last_day + 1):
        days_since_first = (day + 1) - placed_day - first
        if days_since_first >= 0 and days_since_first % interval == 0:
            n += 1
    return n


def livestock_continuation_ev(tiles, day, last_day, prices):
    """Quote-time remaining livestock output vs feed bill if we keep feeding.

    One remaining yield event is treated as one unit at the current quote,
    matching rescue_feed_action. Animals eat one wheat per day. Used by
    feed_roi_gate; callers that pass H4's off flag never see this.
    """
    wheat_q = prices.get("WHEAT") or MARKET_PARAMS["WHEAT"]["base"]
    days_left = max(0, last_day - day + 1)
    n_animals = 0
    prod_value = 0.0
    for row in tiles or []:
        for tile in row:
            if not (isinstance(tile, dict) and "animal" in tile):
                continue
            n_animals += 1
            animal = tile["animal"]
            spec = ANIMALS[animal]
            product = spec["product"]
            quote = prices.get(product) or MARKET_PARAMS[product]["base"]
            held = tile.get("yield_units", 0) or 0
            events = remaining_yield_events(
                animal, tile.get("placed_day", day), day, last_day)
            prod_value += events * quote + held * quote
    feed_cost = n_animals * days_left * wheat_q
    return {
        "n_animals": n_animals,
        "days_left": days_left,
        "prod_value": prod_value,
        "feed_cost": feed_cost,
        "stop": n_animals > 0 and prod_value < feed_cost,
    }


def extra_sheep_npv(day, last_day, prices, n=1):
    """Break-even for buying `n` sheep today. Negative if they cannot mature."""
    sheep_q = prices.get("WOOL") or MARKET_PARAMS["WOOL"]["base"]
    wheat_q = prices.get("WHEAT") or MARKET_PARAMS["WHEAT"]["base"]
    first = ANIMALS["SHEEP"]["first_yield_day"]
    if day + first > last_day:
        return -ANIMALS["SHEEP"]["cost"] * n
    events = remaining_yield_events("SHEEP", day, day + 1, last_day)
    days_fed = max(0, last_day - day + 1)
    revenue = events * sheep_q * n
    cost = ANIMALS["SHEEP"]["cost"] * n + days_fed * wheat_q * n
    return revenue - cost


def expansion_npv(day, last_day, prices, n_sheep=3, land_price=None):
    """Quote-time NPV of buying the next quadrant and `n_sheep` extra sheep.

    Does not include wheat-tile opportunity cost (this path keeps existing
    wheat). land_price defaults to the first paid quadrant (NE, $1000).
    """
    if land_price is None:
        land_price = LAND_PRICES[0]
    return extra_sheep_npv(day, last_day, prices, n_sheep) - land_price


def crop_can_mature(crop, day, last_day):
    """Whether a crop planted today still has a first harvest before the end."""
    return day + CROPS[crop]["first_yield_day"] <= last_day


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
        farms = obs.get("farms") or []
        self.opp_farm = farms[1 - self.player] if len(farms) > 1 else None
        self.private = obs["private"]
        self.tiles = self.farm["tiles"]
        self.board = len(self.tiles)
        self.day = obs["day"]
        self.hour = obs["hour"]
        self.turns_per_day = int(cfg.get("turnsPerDay", 24) or 24)
        self.episode_steps = int(cfg.get("episodeSteps", 720) or 720)
        self.shed_capacity = int(cfg.get("shedCapacity", 100) or 100)
        self.step = obs.get("step", self.day * self.turns_per_day + self.hour)
        # E7: the interpreter stops at episodeSteps - 2, so that is the last turn
        # on which any action is processed, and no end-of-day refresh follows it.
        self.final_step = self.episode_steps - 2
        self.turns_left = max(0, self.final_step - self.step)
        self.last_day = self.final_step // self.turns_per_day
        self.money = self.farm["money"]
        self.shed = self.private["shed"]
        self.seeds = self.private["seeds"]
        self.inventories = self.private["inventories"]
        self.hands = self.farm["hands"]
        self.n_units = 1 + len(self.hands)
        self.units = [tuple(self.farm["farmer"])] + [tuple(h) for h in self.hands]
        self.prices = obs["market"]["prices"]
        self.market_inventory = obs["market"]["inventory"]
        self.shops = list((obs.get("town") or {}).get("unlocked_shops") or [])
        self.access = shed_access_tiles(self.board)
        self.owned = [(x, y) for y, row in enumerate(self.tiles)
                      for x, t in enumerate(row) if t != "LOCKED"]
        self.layout_cache = None
        self.crop_plan = {}

    def inv(self, idx):
        return self.inventories[idx] if idx < len(self.inventories) else {}

    def tile(self, x, y):
        return self.tiles[y][x]

    def shed_used(self):
        return sum(self.shed.values())

    def priced_buy(self, item, qty, budget):
        """(cost, qty) for buying a market product without exceeding `budget`.

        The engine quotes each unit at the post-buy inventory, so a large order
        walks up its own price curve; `econ.market.buy_cost` reproduces that
        walk exactly and stops early the same way the engine does.
        """
        inv = self.market_inventory.get(item)
        if inv is None:      # no market view; fall back to the shown quote
            unit = self.prices.get(item, MARKET_PARAMS[item]["base"])
            n = min(qty, int(budget // unit) if unit > 0 else qty)
            return n * unit, n
        cost, bought, _ = buy_cost(item, qty, inv, budget)
        return cost, bought

    def nearest_access(self, pos):
        return min(self.access, key=lambda t: (manhattan(pos, t), t))

    def dist_to_shed(self, pos):
        return min(manhattan(pos, t) for t in self.access)


class Executor:
    """Callable agent. Instances are reused across turns within an episode."""

    def __init__(self, config=None):
        self.cfg = config or Config()
        self._opportunity = None
        self.opportunity_log = []
        self.mix_log = []
        self._displace_tiles = set()
        self._mix_plan = {}
        self._mix_plan_day = -1

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
        if w.step == 0:
            self.mix_log = []
            self._mix_plan = {}
            self._mix_plan_day = -1
        self._maybe_commit_opportunity(w, obs)
        orders = self._market_orders(w)
        tasks = self._tasks(w)
        assignment = self._assign(w, tasks, deadline)
        raw = self._actions(w, assignment, tasks)
        raw = self._finalize(w, raw)
        return {"farmer": raw[0], "hands": raw[1:], "market": orders[:MAX_MARKET_ORDERS]}

    def _committed(self):
        p = self._opportunity
        if p and p.get("id") and p["id"] != "STAY_H4":
            return p
        return None

    def _maybe_commit_opportunity(self, w, obs):
        """Rank packages at dawn; freeze the first non-H4 commit. Flag off is a no-op."""
        cfg = self.cfg
        if not (cfg.opportunity_enabled or cfg.ceiling_convert_enabled):
            return
        if w.step == 0:
            self._opportunity = None
            self.opportunity_log = []
            self._displace_tiles = set()
        if self._committed() is not None:
            return
        if w.hour != 0:
            return
        snap = snapshot_from_obs(obs)
        snap["last_day"] = w.last_day
        ranked = evaluate_opportunities(
            snap, min_npv=cfg.opportunity_min_npv,
            min_expected=cfg.opportunity_min_expected,
            floor_fraction=cfg.opportunity_floor_fraction,
            livestock_reserve=cfg.livestock_reserve,
            land_reserve=cfg.land_reserve)
        if cfg.ceiling_convert_enabled:
            pick = decide_stay_or_convert(
                snap, ranked,
                min_npv=cfg.ceiling_convert_min_npv,
                min_expected=cfg.ceiling_convert_min_expected,
                floor_fraction=cfg.opportunity_floor_fraction,
                livestock_reserve=cfg.livestock_reserve,
                land_reserve=cfg.land_reserve,
                min_deficit=cfg.ceiling_convert_min_deficit)
        else:
            pick = select_opportunity(ranked)
        self._opportunity = pick
        self.opportunity_log.append({
            "day": w.day, "hour": w.hour, "chosen": pick.get("id"),
            "expected": round(pick.get("expected_npv", 0), 2),
            "conservative": round(pick.get("conservative_npv", 0), 2),
            "cost": pick.get("cost"), "reject": pick.get("reject"),
            "reason": pick.get("reason"),
            "decision_reason": pick.get("decision_reason"),
            "top": [p["id"] for p in ranked[1:4]],
        })

    # -- livestock targets --------------------------------------------------
    def _owned_animals(self, w, animal):
        n = sum(1 for row in w.tiles for t in row
                if isinstance(t, dict) and t.get("animal") == animal)
        n += w.shed.get(animal, 0)
        n += sum(w.inv(i).get(animal, 0) for i in range(w.n_units))
        return n

    def _projected_units(self, w, animal, extra=0):
        """Remaining harvest units from current stock plus `extra` new animals.

        Care is counted as a second unit per event when enabled; that is the
        optimistic own-supply number, so the cap binds a little early rather
        than a little late.
        """
        per = 2 if self.cfg.care else 1
        units = 0
        placed = 0
        for row in w.tiles:
            for tile in row:
                if isinstance(tile, dict) and tile.get("animal") == animal:
                    units += remaining_yield_events(
                        animal, tile.get("placed_day", w.day), w.day, w.last_day) * per
                    placed += 1
        floating = extra + self._owned_animals(w, animal) - placed
        if floating > 0:
            units += floating * remaining_yield_events(
                animal, w.day + 1, w.day, w.last_day) * per
        return units

    def _absorption(self, w, item):
        inv = w.market_inventory.get(item, MARKET_I0)
        room = units_until_price(item, inv, self.cfg.livestock_cap_floor)
        town = expected_remaining_demand(
            item, w.day, w.shops, w.turns_per_day, season_days=w.last_day + 1)
        return room + town

    def _can_add_animal(self, w, animal, extra=1):
        if not self.cfg.livestock_cap_enabled:
            return True
        product = ANIMALS[animal]["product"]
        projected = self._projected_units(w, animal, extra=extra)
        if projected > self._absorption(w, product) * self.cfg.livestock_absorb_slack:
            return False
        already = self._projected_units(w, animal, extra=0)
        lookahead = max(1, int(projected - already))
        inv = w.market_inventory.get(product, MARKET_I0)
        mv = marginal_value(product, inv, lookahead=lookahead)
        return mv >= MARKET_PARAMS[product]["base"] * self.cfg.livestock_cap_floor

    def _livestock_targets(self, w):
        cfg = self.cfg
        if w.day < cfg.livestock_start_day:
            return {"GOOSE": 0, "COW": 0, "SHEEP": 0}
        sheep = cfg.sheep
        n_quads = len(w.farm.get("unlocked_quadrants") or [])
        if cfg.sheep_after_land and n_quads > 1:
            sheep += cfg.sheep_after_land
        if cfg.roi_expand_enabled and n_quads > 1:
            sheep += cfg.roi_expand_sheep
        pkg = self._committed()
        if pkg and pkg.get("sheep_bonus"):
            if not pkg.get("buy_land") or n_quads > 1:
                sheep += pkg["sheep_bonus"]
        if cfg.sheep_yarn_bonus and "YARN_STORE" in (w.shops or []):
            sheep += cfg.sheep_yarn_bonus
        cows = cfg.cows
        if pkg and pkg.get("cow_bonus"):
            if not pkg.get("buy_land") or n_quads > 1:
                cows += pkg["cow_bonus"]
        raw = {"GOOSE": cfg.geese, "COW": cows, "SHEEP": sheep}
        if not cfg.livestock_cap_enabled:
            return raw
        out = {}
        for animal, want in raw.items():
            have = self._owned_animals(w, animal)
            n = have
            while n < want:
                if not self._can_add_animal(w, animal, extra=n - have + 1):
                    break
                n += 1
            out[animal] = n
        return out

    def _extra_crop(self):
        pkg = self._committed()
        if pkg and pkg.get("extra_crop"):
            extra = (pkg["extra_crop"] or "").upper()
            return extra if extra in CROPS else ""
        extra = (self.cfg.extra_crop or "").upper()
        return extra if extra in CROPS else ""

    def _crop_for_tile(self, tile, board, world=None):
        if world is not None and getattr(world, "crop_plan", None):
            planned = world.crop_plan.get(tile)
            if planned:
                return planned
        extra = self._extra_crop()
        if extra and quadrant_of(tile[0], tile[1], board) != "NW":
            return extra
        pkg = self._committed()
        if pkg and pkg.get("displace_crop") and tile in self._displace_tiles:
            return pkg["displace_crop"]
        return self.cfg.crops[0] if self.cfg.crops else None

    def _snap_from_world(self, w):
        opp_tiles = None
        if w.opp_farm:
            opp_tiles = w.opp_farm.get("tiles")
        return {
            "day": w.day,
            "last_day": w.last_day,
            "money": w.money,
            "prices": dict(w.prices or {}),
            "inventory": dict(w.market_inventory or {}),
            "shops": list(w.shops or []),
            "n_quads": len(w.farm.get("unlocked_quadrants") or []),
            "own_tiles": w.tiles,
            "own_shed": dict(w.shed or {}),
            "opp_tiles": opp_tiles,
            # Elite-mix melon cap (None = E77 conservative). M18 sets 18.
            "melon_policy": getattr(self.cfg, "melon_policy", None),
            "melon_fallback": getattr(self.cfg, "melon_fallback", "pa"),
        }

    def _fill_elite_crop_plan(self, w, crop_tiles):
        """Assign one crop per empty crop tile from the state-based mix.

        Livestock slots are untouched. Pending counts stop a single hour from
        planting an entire melon glut. Nested import keeps H4's default path
        from loading the candidate engine.
        """
        from .econ import engine as elite_engine
        if not any(w.tile(p[0], p[1]) is None for p in crop_tiles):
            w.crop_plan = {}
            return
        if w.hour == 0 or w.day != self._mix_plan_day:
            self._mix_plan = {}
            self._mix_plan_day = w.day
        pending = {}
        for crop in self._mix_plan.values():
            pending[crop] = pending.get(crop, 0) + 1
        snap = self._snap_from_world(w)
        plan = dict(self._mix_plan)
        for pos in crop_tiles:
            if w.tile(pos[0], pos[1]) is not None:
                continue
            if pos in plan:
                continue
            chosen, ranked = elite_engine.choose_tile_use(
                snap, pending=pending, crop_only=True)
            crop = chosen.get("use") if chosen and not chosen.get("reject") else None
            if crop not in CROPS:
                crop = None
            if crop:
                plan[pos] = crop
                pending[crop] = pending.get(crop, 0) + 1
            if w.hour == 0 and len(self.mix_log) < 500:
                straw = next((r for r in ranked if r["use"] == "STRAWBERRY"), {})
                melon = next((r for r in ranked if r["use"] == "MELON"), {})
                wheat = next((r for r in ranked if r["use"] == "WHEAT"), {})
                others = [r.get("npv") or 0 for r in ranked if r.get("use") != crop]
                opp_cost = max(others) if others else 0
                self.mix_log.append({
                    "day": w.day, "hour": w.hour, "tile": list(pos),
                    "crop": crop, "reject": chosen.get("reject") if chosen else None,
                    "reason": (chosen or {}).get("reason"),
                    "cons_npv": round((chosen or {}).get("npv") or 0, 2),
                    "exp_npv": round((chosen or {}).get("expected_npv") or 0, 2),
                    "revenue": round((chosen or {}).get("revenue") or 0, 2),
                    "cost": round((chosen or {}).get("cost") or 0, 2),
                    "absorption": (chosen or {}).get("absorption"),
                    "maturity": CROPS[crop]["first_yield_day"] if crop else None,
                    "opp_cost": round(opp_cost, 2),
                    "velocity_gap": bool((chosen or {}).get("velocity_gap")),
                    "pending": dict(pending),
                    "melon_justified": elite_engine.melon_justified_tiles(snap)[0],
                    "straw_cons": round(straw.get("npv") or 0, 2),
                    "straw_exp": round(straw.get("expected_npv") or 0, 2),
                    "melon_cons": round(melon.get("npv") or 0, 2),
                    "melon_exp": round(melon.get("expected_npv") or 0, 2),
                    "wheat_cons": round(wheat.get("npv") or 0, 2),
                    "money": round(float(w.money), 2),
                })
                # Conservative reject / expected accept on the runner-up premium.
                for row in ranked:
                    if row.get("velocity_gap"):
                        self.mix_log[-1].setdefault("gaps", []).append({
                            "use": row["use"], "reject": row.get("reject"),
                            "exp_npv": round(row.get("expected_npv") or 0, 2),
                        })
        w.crop_plan = plan
        self._mix_plan = plan

    def _pinned_livestock_slots(self, w, wanted, ordered):
        """Keep animals on tiles they already occupy; fill remaining nearest.

        Unlocking NE changes the nearest-N owned set. Reassigning livestock
        onto the new nearest tiles orphans the old pastures (no FEED → escape).
        """
        want_left = {a: 0 for a in ANIMALS}
        for animal in wanted:
            want_left[animal] = want_left.get(animal, 0) + 1
        occupied = {}
        owned = set(w.owned)
        for y, row in enumerate(w.tiles):
            for x, t in enumerate(row):
                if (x, y) in owned and isinstance(t, dict) and t.get("animal"):
                    occupied[(x, y)] = t["animal"]
        slots = {}
        for pos in ordered:
            kind = occupied.get(pos)
            if kind and want_left.get(kind, 0) > 0:
                slots[pos] = kind
                want_left[kind] -= 1
        remaining = []
        for animal in ("GOOSE", "COW", "SHEEP"):
            remaining.extend([animal] * want_left.get(animal, 0))
        for pos in ordered:
            if not remaining:
                break
            if pos in slots:
                continue
            slots[pos] = remaining.pop(0)
        return slots

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
        targets = self._livestock_targets(w)
        wanted = (["GOOSE"] * targets["GOOSE"] + ["COW"] * targets["COW"]
                  + ["SHEEP"] * targets["SHEEP"])
        extra = self._extra_crop()
        pkg = self._committed()
        pin = extra or cfg.pin_livestock or (
            cfg.roi_expand_enabled and len(w.farm.get("unlocked_quadrants") or []) > 1
        ) or (pkg and pkg.get("pin"))
        tpu = cfg.tiles_per_unit
        if pkg and pkg.get("tiles_per_unit"):
            tpu = pkg["tiles_per_unit"]
        if pin:
            slots = self._pinned_livestock_slots(w, wanted, ordered)
            nw_crop = [p for p in ordered if p not in slots
                       and quadrant_of(p[0], p[1], w.board) == "NW"]
            other_crop = [p for p in ordered if p not in slots
                          and quadrant_of(p[0], p[1], w.board) != "NW"]
            crew = max(1, cfg.hands_per_day + 1)
            limit = min(cfg.max_crop_tiles, int(crew * tpu))
            crop_tiles = nw_crop[:limit]
            leftover = limit - len(crop_tiles)
            if leftover > 0:
                crop_tiles = crop_tiles + other_crop[:leftover]
        else:
            slots = {}
            for animal, pos in zip(wanted, ordered):
                slots[pos] = animal
            crew = max(1, cfg.hands_per_day + 1)
            limit = min(cfg.max_crop_tiles, int(crew * tpu))
            crop_tiles = ordered[len(slots):][:limit]
        w.crop_plan = {}
        if cfg.elite_mix_enabled:
            self._fill_elite_crop_plan(w, crop_tiles)
        if pkg and pkg.get("displace_n") and pkg.get("displace_crop") and crop_tiles:
            n = min(int(pkg["displace_n"]), len(crop_tiles))
            self._displace_tiles = set(crop_tiles[-n:])
        else:
            self._displace_tiles = set()
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
        extra = self._extra_crop()
        for i, (x, y) in enumerate(crop_tiles):
            tile = w.tile(x, y)
            if tile is None:
                if cfg.elite_mix_enabled or extra:
                    crop = self._crop_for_tile((x, y), w.board, world=w)
                else:
                    crop = cfg.crops[i % len(cfg.crops)] if cfg.crops else None
                if (crop and seeds.get(crop, 0) > 0 and self._can_mature(w, crop)
                        and plant_hour_allowed(w.hour, cfg.plant_latest_hour)):
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
            product = animal["product"]
            base = MARKET_PARAMS[product]["base"]
            quote = w.prices.get(product, base)
            if not harvest_deferred(
                    quote, base, held, animal["max_held"],
                    cfg.harvest_defer_enabled, cfg.harvest_defer_floor_fraction,
                    cfg.harvest_defer_hold_full, w.day, w.last_day,
                    cfg.sell_defer_force_days, product,
                    cfg.harvest_defer_wool_only, cfg.harvest_defer_force_days):
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
        """E7: a crop planted first_yield_day before the end still pays.

        It will not reach full yield, but watering adds units immediately, so a
        late planting is harvested short rather than wasted.
        """
        return w.day + CROPS[crop]["first_yield_day"] <= w.last_day

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
        closing = self._endgame_action(w, pos, inv)
        if closing is not None:
            return closing
        rescue = self._rescue_feed(w, pos, inv)
        if rescue is not None:
            return rescue
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
        return feed_pickup_qty(
            w.shed.get("WHEAT", 0), n_animals, self.cfg.feed_pickup_cap)

    def _rescue_feed(self, w, pos, inv):
        """On-tile last-day FEED if E47 class-C conditions hold. Default off."""
        if not self.cfg.endgame_rescue_feed:
            return None
        tile = w.tile(*pos)
        if not (isinstance(tile, dict) and "animal" in tile):
            return None
        animal = tile["animal"]
        product = ANIMALS[animal]["product"]
        quote = w.prices.get(product, MARKET_PARAMS[product]["base"])
        n = remaining_yield_events(
            animal, tile.get("placed_day", 0), w.day + 1, w.last_day)
        kind = rescue_feed_action(
            True, w.day, w.last_day, bool(tile.get("fed_today")),
            int(tile.get("consecutive_unfed", 0)),
            inv.get("WHEAT", 0), n * quote)
        if kind == "FEED":
            return ["FEED"]
        return None

    def _endgame_action(self, w, pos, inv):
        """In the closing turns the only thing worth doing is banking stock.

        E7 established that there is no end-of-day drop after the final turn, so
        anything still in a farmer's hands is simply lost. Unit actions do resolve
        before the market, though, so a DROP and a SELL on the same last turn
        still convert carried produce into money.
        """
        distance = w.dist_to_shed(pos)
        if w.turns_left > distance + 1:
            return None
        if inv:
            if is_shed_adjacent(pos, w.board):
                return ["DROP"]
            return self._step_toward(pos, w.nearest_access(pos))
        if w.turns_left == 0:
            return ["PASS"]     # nothing picked up now can ever reach the shed
        return None

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
        value = sum((w.prices.get(item, 0) or 0) * n for item, n in inv.items())
        if shed_trip_justified(
                carried, value, w.dist_to_shed(pos), w.hour, w.turns_per_day,
                self.cfg.drop_threshold, self.cfg.move_ev_enabled,
                self.cfg.min_trip_value_per_step):
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
        """Plan the turn's orders against one shared purse.

        Every buy draws from the same running balance, in priority order, so a
        plan that wants land and livestock and seed on the same day is forced to
        choose instead of committing the same dollar three times. Sale revenue
        is deliberately not counted: sells do land earlier in the queue and do
        fund later buys, but the price they clear at depends on what the
        opponent dumps in the same lockstep, and spending money we only hope to
        receive is how the farm starved.
        """
        cfg = self.cfg
        orders = []
        purse = w.money

        # The final day still has a full harvest and the liquidation on it, so
        # hire right through it unless a conversion flag skips late hires.
        skip_hire = cfg.liquidate_stop_hire and self._liquidating(w)
        if (not skip_hire and w.hour == cfg.hire_hour
                and w.day <= w.last_day and cfg.hands_per_day > 0):
            n = min(cfg.hands_per_day, MAX_MARKET_ORDERS)
            cost = cumulative_hire_cost(n)
            if purse - cost >= cfg.hire_reserve:
                orders.extend([["HIRE"]] * n)
                purse -= cost

        n_animals = sum(1 for row in w.tiles for t in row
                        if isinstance(t, dict) and "animal" in t)
        feed_target = n_animals * cfg.feed_buffer
        orders.extend(self._sell_orders(w, feed_target))

        # Feed outranks every other purchase: two missed days and the animal is
        # gone along with the capital that bought it. It draws on the whole
        # purse for that reason. Conversion flags may skip the restock.
        skip_feed_buy = cfg.liquidate_stop_feed_buy and self._liquidating(w)
        if cfg.feed_roi_gate:
            ev = livestock_continuation_ev(w.tiles, w.day, w.last_day, w.prices)
            if ev["stop"]:
                skip_feed_buy = True
        carried = 0
        if cfg.feed_count_carried:
            carried = sum(w.inv(i).get("WHEAT", 0) for i in range(w.n_units))
        wheat_short = wheat_feed_short(
            w.shed.get("WHEAT", 0), carried, n_animals, cfg.feed_buffer,
            cfg.feed_count_carried)
        if (not skip_feed_buy) and n_animals and wheat_short > 0:
            room = w.shed_capacity - w.shed_used()
            want = max(0, min(wheat_short, room))
            cost, qty = w.priced_buy("WHEAT", want, purse)
            if qty:
                orders.append(["BUY_PRODUCT", "WHEAT", qty])
                purse -= cost

        orders.extend(self._acquisition_orders(w, purse))
        return orders

    def _liquidating(self, w):
        return w.day >= w.last_day - self.cfg.liquidate_before_end

    def _sell_orders(self, w, feed_target):
        cfg = self.cfg
        liquidating = self._liquidating(w)
        out = []
        for item in PRODUCTS:
            qty = w.shed.get(item, 0)
            if item == "WHEAT" and not liquidating:
                qty -= feed_target
            if qty <= 0:
                continue
            base = MARKET_PARAMS[item]["base"]
            quote = w.prices.get(item, base)
            if sale_justified(
                    quote, base, w.day, w.last_day, w.shed_used(), w.shed_capacity,
                    cfg.sell_floor_fraction, liquidating, cfg.sell_defer_enabled,
                    cfg.sell_defer_force_days, cfg.sell_defer_shed_frac):
                n = capped_sale_qty(
                    qty, item, w.market_inventory.get(item),
                    cfg.sale_qty_floor, cfg.sale_qty_enabled,
                    w.day, w.last_day, w.shed_used(), w.shed_capacity,
                    cfg.sale_qty_force_days, cfg.sale_qty_shed_frac)
                if n > 0:
                    out.append(["SELL", item, n])
        return out

    def _acquisition_orders(self, w, purse):
        """Capital spending, cheapest payback first, out of what feed left over.

        Order matters twice over: the engine fills orders by index, so earlier
        entries get the money, and each entry here also shrinks the purse the
        later ones see.
        """
        cfg = self.cfg
        out = []
        slots, crop_tiles = self._layout(w)
        if self._liquidating(w):
            return out

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
            # E7: an animal placed later than first_yield_day before the end
            # never produces anything at all.
            if short <= 0 or w.day + ANIMALS[animal]["first_yield_day"] > w.last_day:
                continue
            cost = ANIMALS[animal]["cost"]
            # An animal also commits us to feeding it for the rest of the run,
            # so it has to clear the reserve rather than merely be affordable.
            qty = min(short, int(max(0, purse - cfg.livestock_reserve) // cost))
            if qty and w.shed_used() < w.shed_capacity:
                out.append(["BUY_ANIMAL", animal, qty])
                purse -= qty * cost

        if cfg.crops or cfg.elite_mix_enabled:
            extra = self._extra_crop()
            if cfg.elite_mix_enabled or extra:
                empty_by = {}
                for (x, y) in crop_tiles:
                    if w.tile(x, y) is None:
                        crop = self._crop_for_tile((x, y), w.board, world=w)
                        if crop:
                            empty_by[crop] = empty_by.get(crop, 0) + 1
                wanted_seeds = list(empty_by.items())
            else:
                empty = sum(1 for (x, y) in crop_tiles if w.tile(x, y) is None)
                wanted_seeds = []
                for crop in cfg.crops:
                    share = -(-empty // len(cfg.crops))          # ceil
                    wanted_seeds.append((crop, share))
            for crop, empty in wanted_seeds:
                if not self._can_mature(w, crop):
                    continue
                need = min(empty, cfg.seed_batch) - w.seeds.get(crop, 0)
                cost = CROPS[crop]["seed"]
                qty = min(need, int(max(0, purse - cfg.seed_reserve) // cost))
                if qty > 0:
                    out.append(["BUY_SEED", crop, qty])
                    purse -= qty * cost

        # Land last. It earns nothing by itself -- it only makes room for stock
        # and crops we then have to afford, and buying it first is what starved
        # the livestock in the screening run.
        bought = len(w.farm["unlocked_quadrants"]) - 1     # NW is free
        want_land = bought < cfg.buy_land
        if cfg.roi_expand_enabled and bought < 1:
            npv = expansion_npv(w.day, w.last_day, w.prices, cfg.roi_expand_sheep,
                                LAND_PRICES[0])
            need = (LAND_PRICES[0] + cfg.roi_expand_sheep * ANIMALS["SHEEP"]["cost"]
                    + cfg.livestock_reserve)
            if npv > cfg.roi_expand_min_npv and purse >= need:
                want_land = True
        pkg = self._committed()
        if pkg and pkg.get("buy_land") and bought < pkg["buy_land"]:
            want_land = True
        if want_land:
            price = LAND_PRICES[bought]
            # Only worth it while there is still season left to farm it.
            day_ok = cfg.land_min_day < 0 or w.day >= cfg.land_min_day
            cash_ok = cfg.land_min_money <= 0 or purse >= cfg.land_min_money
            # ROI expansion and the opportunity layer use NPV as the time gate;
            # calendar buy_land keeps the original half-season cap.
            opp_land = bool(pkg and pkg.get("buy_land"))
            season_ok = (cfg.roi_expand_enabled and cfg.buy_land == 0) or opp_land or (
                w.day <= w.last_day // 2)
            if (purse - price >= cfg.land_reserve and season_ok
                    and day_ok and cash_ok):
                out.append(["BUY_LAND"])
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
