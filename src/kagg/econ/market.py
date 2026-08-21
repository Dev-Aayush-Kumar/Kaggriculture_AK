"""Market model: exact price replication plus the derived quantities the planner needs.

`price()` is a bit-for-bit reimplementation of the engine's `market_price()`; the
rest of this module builds on it to answer the questions the agent actually asks:
what is the next unit worth, how much can we sell before the price collapses, and
how fast is the town draining supply.
"""

import math

from .tables import (MARKET_PARAMS, MARKET_I0, PRICE_FLOOR, HINGE_GAIN,
                     PRODUCTS, SHOPS, TOWN_CENTER_PRODUCTS)


def _shape(func, x, T=None):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price(item, inventory, params=None):
    """Sale price of `item` at the given market inventory. Mirrors engine market_price()."""
    p = (params or MARKET_PARAMS)[item]
    base, I0, T = p["base"], p["I0"], p["T"]
    if inventory < I0:
        f = p["below_func"]
        amp = p["below_target"] * base / _shape(f, T, T)
        v = base + amp * _shape(f, I0 - inventory, T)
    else:
        f = p["above_func"]
        amp = p["above_target"] * base / _shape(f, T, T)
        v = base - amp * _shape(f, inventory - I0, T)
    return max(PRICE_FLOOR, int(round(v)))


def buy_price(item, inventory, params=None):
    """BUY_PRODUCT is quoted at the post-buy inventory, so a buy/sell round trip nets zero."""
    return price(item, inventory - 1, params)


def sell_revenue(item, qty, inventory, params=None):
    """Revenue for dumping `qty` units now. Units sold at the $1 floor do not add supply."""
    inv, rev = inventory, 0
    for _ in range(qty):
        p = price(item, inv, params)
        rev += p
        if p > PRICE_FLOOR:
            inv += 1
    return rev, inv


def buy_cost(item, qty, inventory, budget=None, params=None):
    """Cost of buying `qty` units. Stops early if `budget` runs out, like the engine."""
    inv, cost, bought = inventory, 0, 0
    for _ in range(qty):
        p = buy_price(item, inv, params)
        if budget is not None and cost + p > budget:
            break
        cost += p
        inv -= 1
        bought += 1
    return cost, bought, inv


def marginal_value(item, inventory, lookahead=1, params=None):
    """Average $/unit for the next `lookahead` units. This is the number the task
    scorer uses, so labour automatically drains away from collapsed markets."""
    rev, _ = sell_revenue(item, max(1, lookahead), inventory, params)
    return rev / max(1, lookahead)


def units_until_price(item, inventory, floor_fraction=0.25, params=None):
    """How many units we can sell before the price falls below `floor_fraction` of base.
    Used to size production lines against remaining absorption."""
    base = (params or MARKET_PARAMS)[item]["base"]
    target = base * floor_fraction
    inv, n = inventory, 0
    while n < 20000:
        p = price(item, inv, params)
        if p < target:
            break
        n += 1
        if p > PRICE_FLOOR:
            inv += 1
        else:
            break
    return n


# ----------------------------------------------------------------- town demand

def shop_drain_per_tick(unlocked_shops, item):
    """Units of `item` removed per shop tick (every townShopSellInterval turns)."""
    total = 0
    for name in unlocked_shops:
        products = SHOPS.get(name)
        if products and item in products:
            total += 2 if len(products) == 1 else 1
    return total


def town_drain_per_day(unlocked_shops, item, turns_per_day=24,
                       shop_interval=4, center_interval=24):
    """Units of `item` the town removes per day at the current shop set."""
    shop_ticks = turns_per_day // shop_interval
    center_ticks = turns_per_day / center_interval
    drain = shop_drain_per_tick(unlocked_shops, item) * shop_ticks
    if item in TOWN_CENTER_PRODUCTS:
        drain += center_ticks
    return drain


def next_unlock_day(day, unlock_interval=3, n_unlocked=0, max_instances=8):
    """Day on which the next shop instance becomes active, or None if unlocking is done."""
    if n_unlocked >= max_instances:
        return None
    d = day + 1
    while d <= 30:
        if d % unlock_interval == 0:
            return d
        d += 1
    return None


def project_inventory(item, inventory, days, unlocked_shops, own_sales_per_day=0.0,
                      opp_sales_per_day=0.0, turns_per_day=24):
    """Inventory `days` ahead assuming the current shop set and given sale rates.
    Deliberately ignores future unlocks -- the caller re-runs this each day."""
    drain = town_drain_per_day(unlocked_shops, item, turns_per_day)
    net = (own_sales_per_day + opp_sales_per_day - drain) * days
    return inventory + net


def expected_remaining_demand(item, day, unlocked_shops, turns_per_day=24,
                              season_days=30, unlock_interval=3, max_instances=8):
    """Units of `item` the town will consume between `day` and the end of the season.

    Counts the currently-unlocked shops exactly and adds the expectation over the
    remaining random draws (uniform with replacement over the 8 shop types).
    """
    remaining_days = max(0, season_days - day)
    known = town_drain_per_day(unlocked_shops, item, turns_per_day) * remaining_days

    n_unlocked = len(unlocked_shops)
    shop_ticks = turns_per_day // 4
    per_shop_day = sum(
        (2 if len(p) == 1 else 1) for p in SHOPS.values() if item in p
    ) / len(SHOPS) * shop_ticks

    future = 0.0
    d = day + 1
    while d <= season_days and n_unlocked < max_instances:
        if d % unlock_interval == 0:
            n_unlocked += 1
            future += per_shop_day * (season_days - d)
        d += 1
    return known + future
