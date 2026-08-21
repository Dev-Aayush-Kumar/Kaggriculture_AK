"""Action vocabulary and legality checks.

Every guard in `check_unit_action` is a transcription of the corresponding guard
in `_apply_unit_action` in the engine, in the same order. The contract is:

    check_unit_action(...) == OK   <=>   the engine mutates state

`tests/test_action_rules.py` asserts that equivalence over a real episode, so a
divergence is a test failure rather than a silent planning error.

Two uses: the executor routes every action through here before emitting it, and
the research harness uses it to classify wasted turns.
"""

from .econ.tables import ANIMALS, CROPS, PRODUCTS, shed_access_tiles

OK = "ok"

MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

# The engine raises on a non-integer quantity rather than no-opping, which would
# abort the episode, so the executor must never emit one.
_QTY_OPS = ("PICKUP", "PLACE")

MARKET_OPS = ("BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "SELL", "HIRE", "BUY_LAND")
BUYABLE_PRODUCTS = ("WHEAT", "FERTILIZER")

# Coarse buckets for the routing experiment's action budget.
CATEGORY = {
    "NORTH": "move", "SOUTH": "move", "EAST": "move", "WEST": "move",
    "PASS": "idle",
    "PLANT": "plant", "WATER": "water", "HARVEST": "harvest",
    "FERTILIZE": "fertilize", "DIG": "clear",
    "FEED": "feed", "CARE": "care", "COLLECT_FERTILIZER": "fertilizer",
    "BUILD_COOP": "build", "BUILD_PASTURE": "build",
    "PICKUP": "logistics", "DROP": "logistics", "PLACE": "logistics",
}
CATEGORIES = ("move", "idle", "plant", "water", "harvest", "fertilize", "clear",
              "feed", "care", "fertilizer", "build", "logistics", "wasted")

UNIT_OPS = frozenset(CATEGORY)


def category(action):
    """Bucket an action for accounting. Unknown ops count as wasted."""
    if not isinstance(action, (list, tuple)) or not action:
        return "wasted"
    return CATEGORY.get(action[0], "wasted")


def unit_position(farm, idx):
    """idx 0 is the main farmer, 1+ index into `hands`."""
    if idx == 0:
        return farm["farmer"]
    hands = farm["hands"]
    return hands[idx - 1] if idx - 1 < len(hands) else None


def unit_inventory(private, idx):
    inventories = private["inventories"]
    return inventories[idx] if idx < len(inventories) else {}


def is_shed_adjacent(pos, board_size=10):
    return (pos[0], pos[1]) in set(shed_access_tiles(board_size))


def blocked_plant_crops(unit_actions, seeds):
    """Crops whose PLANT requests the interpreter will drop wholesale this turn.

    The engine counts every PLANT request across farmer and hands and, if the
    total for a crop exceeds the seeds on hand, converts *all* of them to PASS.
    """
    demand = {}
    for a in unit_actions:
        if isinstance(a, (list, tuple)) and len(a) >= 2 and a[0] == "PLANT":
            demand[a[1]] = demand.get(a[1], 0) + 1
    return {crop for crop, n in demand.items() if n > seeds.get(crop, 0)}


def _qty(action, default=1):
    if len(action) < 3:
        return default
    try:
        return int(action[2])
    except (TypeError, ValueError):
        return None


def check_unit_action(action, farm, private, idx, day, board_size=10,
                      shed_capacity=100, blocked_crops=()):
    """Return OK if the engine would act on this action, else a reason string."""
    if not isinstance(action, (list, tuple)) or not action:
        return "malformed"
    op = action[0]
    pos = unit_position(farm, idx)
    if pos is None:
        return "no_such_unit"
    fx, fy = pos[0], pos[1]
    inv = unit_inventory(private, idx)

    if op in MOVES:
        dx, dy = MOVES[op]
        nx, ny = fx + dx, fy + dy
        if not (0 <= nx < board_size and 0 <= ny < board_size):
            return "off_board"
        return OK

    if op == "PASS":
        return "pass"

    tile = farm["tiles"][fy][fx]

    # Shed ops resolve before the LOCKED guard: three of the four shed-access
    # tiles start locked, and the shed itself is always owned.
    if op == "DROP":
        if not is_shed_adjacent(pos, board_size):
            return "not_shed_adjacent"
        if not inv:
            return "nothing_to_drop"
        return OK

    if op == "PICKUP":
        if not is_shed_adjacent(pos, board_size):
            return "not_shed_adjacent"
        if len(action) < 2:
            return "malformed"
        n = _qty(action)
        if n is None:
            return "malformed"
        if n <= 0:
            return "bad_quantity"
        if private["shed"].get(action[1], 0) <= 0:
            return "not_in_shed"
        return OK

    if op == "PLACE":
        if len(action) < 2:
            return "malformed"
        item = action[1]
        if (item in ANIMALS and isinstance(tile, dict)
                and tile.get("kind") == ANIMALS[item]["structure"]
                and "animal" not in tile):
            return OK if inv.get(item, 0) >= 1 else "animal_not_carried"
        if not is_shed_adjacent(pos, board_size):
            return "not_shed_adjacent"
        n = _qty(action)
        if n is None:
            return "malformed"
        if n <= 0:
            return "bad_quantity"
        if inv.get(item, 0) <= 0:
            return "not_carried"
        if sum(private["shed"].values()) >= shed_capacity:
            return "shed_full"
        return OK

    # Everything below mutates the tile the unit stands on.
    if tile == "LOCKED":
        return "locked_tile"

    if op == "PLANT":
        if len(action) < 2:
            return "malformed"
        crop = action[1]
        if crop not in CROPS:
            return "unknown_crop"
        if crop in blocked_crops:
            return "plant_contended"
        if tile is not None:
            return "tile_occupied"
        if private["seeds"].get(crop, 0) <= 0:
            return "no_seed"
        return OK

    if op == "WATER":
        if not _is_plant(tile):
            return "not_a_plant"
        if tile["watered_today"]:
            return "already_watered"
        return OK

    if op == "HARVEST":
        if not isinstance(tile, dict):
            return "nothing_here"
        if tile.get("yield_units", 0) <= 0:
            return "no_yield"
        if tile.get("kind") == "PLANT":
            if day - tile["planted_day"] < CROPS[tile["crop"]]["first_yield_day"]:
                return "immature"
            return OK
        if "animal" in tile:
            return OK
        return "not_harvestable"

    if op == "FERTILIZE":
        if not _is_plant(tile):
            return "not_a_plant"
        if inv.get("FERTILIZER", 0) < 1:
            return "no_fertilizer"
        return OK

    if op == "DIG":
        if tile is None:
            return "nothing_to_dig"
        if isinstance(tile, dict) and "animal" in tile:
            return "animal_present"
        return OK

    if op in ("BUILD_COOP", "BUILD_PASTURE"):
        if tile is not None:
            return "tile_occupied"
        return OK

    if op == "FEED":
        if not _is_animal(tile):
            return "no_animal"
        if tile["fed_today"]:
            return "already_fed"
        if inv.get("WHEAT", 0) < 1:
            return "no_wheat"
        return OK

    if op == "COLLECT_FERTILIZER":
        if not _is_animal(tile):
            return "no_animal"
        if not tile["fertilizer_available"]:
            return "no_fertilizer_ready"
        return OK

    if op == "CARE":
        if not _is_animal(tile):
            return "no_animal"
        if tile["cared_today"]:
            return "already_cared"
        return OK

    return "unknown_op"


def _is_plant(tile):
    return isinstance(tile, dict) and tile.get("kind") == "PLANT"


def _is_animal(tile):
    return isinstance(tile, dict) and "animal" in tile


def parse_market_order(order):
    """Mirror of the engine's `_parse_order`; None means the engine discards it."""
    if not isinstance(order, (list, tuple)) or not order:
        return None
    op = order[0]
    if op in ("HIRE", "BUY_LAND"):
        return {"type": op}
    if op in ("BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "SELL"):
        if len(order) < 3:
            return None
        try:
            n = int(order[2])
        except (TypeError, ValueError):
            return None
        if n <= 0:
            return None
        item = order[1]
        if op == "SELL" and item not in PRODUCTS:
            return None
        if op == "BUY_PRODUCT" and item not in BUYABLE_PRODUCTS:
            return None
        if op == "BUY_SEED" and item not in CROPS:
            return None
        if op == "BUY_ANIMAL" and item not in ANIMALS:
            return None
        return {"type": op, "item": item, "remaining": n}
    return None
