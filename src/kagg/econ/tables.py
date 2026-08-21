"""Static game tables mirrored from kaggle_environments/envs/kaggriculture/kaggriculture.py.

Every value here is copied from the engine source and is asserted equal to it by
tests/test_market_parity.py. Never edit these by hand without re-running that test.
"""

CROPS = {
    "WHEAT":      {"seed": 10,  "first_yield_day": 2,  "max_yield_day": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first_yield_day": 2,  "max_yield_day": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first_yield_day": 8,  "max_yield_day": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER"]

# Only these two can be re-acquired with BUY_PRODUCT.
BUYABLE_PRODUCTS = ("WHEAT", "FERTILIZER")

MARKET_I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0

MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "I0": MARKET_I0, "T": 400, "below_func": "sqrt",   "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base":  35, "I0": MARKET_I0, "T": 450, "below_func": "hinge",  "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base":  60, "I0": MARKET_I0, "T": 200, "below_func": "hinge",  "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": MARKET_I0, "T": 100, "below_func": "sqrt",   "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "I0": MARKET_I0, "T": 300, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base":  50, "I0": MARKET_I0, "T": 332, "below_func": "hinge",  "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "I0": MARKET_I0, "T": 122, "below_func": "sqrt",   "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "I0": MARKET_I0, "T": 105, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": MARKET_I0, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}

TOWN_CENTER_PRODUCTS = [p for p in PRODUCTS if p != "FERTILIZER"]
MAX_SHOP_INSTANCES = 8

LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]

FARM_HAND_COST_MULT = 1

MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

# Default configuration values (kaggriculture.json).
DEFAULTS = {
    "episodeSteps": 720,
    "boardSize": 10,
    "startingMoney": 3000,
    "maxMarketOrdersPerTurn": 10,
    "turnsPerDay": 24,
    "shedCapacity": 100,
    "weedSpawnChance": 0.005,
    "townShopUnlockInterval": 3,
    "townShopSellInterval": 4,
    "townCenterSellInterval": 24,
    "farmHandCostMult": 1,
}


def fib(n):
    """Engine indexing: fib(0)=1, fib(1)=1, fib(2)=2, fib(3)=3, fib(4)=5, ..."""
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hire_cost(n_already_today, mult=FARM_HAND_COST_MULT):
    return mult * fib(n_already_today)


def cumulative_hire_cost(n_hands, mult=FARM_HAND_COST_MULT):
    """Total cost of hiring n_hands in one day."""
    return sum(hire_cost(i, mult) for i in range(n_hands))


def quadrant_of(x, y, board_size=10):
    half = board_size // 2
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def shed_access_tiles(board_size=10):
    """The four inner-corner tiles around the shed, in NWSE order."""
    half = board_size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]
