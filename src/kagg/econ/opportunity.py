"""Opportunity NPV: quote-walked, demand-capped, opponent-aware packages.

Pure functions. The H4 executor never imports behaviour from here unless
`opportunity_enabled` is on. Formulas follow kaggle_reference/README.md and
the mirrored tables in `kagg.econ.tables` / `kagg.econ.market`.

Two revenue numbers are always produced:

    expected     — sell our units into the current inventory (care/yield at
                   the engine's scheduled amounts, H4 does CARE)
    conservative — opponent visible remaining output is sold first, then our
                   units; livestock care bonus is ignored (1 unit/event)

STAY_H4 is the zero-NPV default. A package is accepted only when conservative
NPV clears the configured floor. Missing observation => reject, stay H4.
"""

from .market import (MARKET_I0, expected_remaining_demand, sell_revenue,
                     units_until_price)
from .tables import ANIMALS, CROPS, LAND_PRICES, MARKET_PARAMS, SHOPS


CROP_PRODUCT = {name: name for name in CROPS}
ANIMAL_PRODUCT = {name: spec["product"] for name, spec in ANIMALS.items()}

STAY = {
    "id": "STAY_H4",
    "label": "stay H4",
    "expected_npv": 0.0,
    "conservative_npv": 0.0,
    "cost": 0.0,
    "land_cost": 0.0,
    "latest_day": 99,
    "earliest_payoff_day": 0,
    "extra_crop": "",
    "buy_land": 0,
    "sheep_bonus": 0,
    "displace_crop": "",
    "displace_n": 0,
    "tiles_per_unit": None,
    "pin": False,
    "crop_tiles": 0,
    "cow_bonus": 0,
    "expected_yield_units": 0,
    "conservative_revenue": 0.0,
    "feed_cost": 0.0,
    "tile_opportunity_cost": 0.0,
    "labor_cost": 0.0,
    "engine_effect": "none",
    "payback_risk": 0.0,
    "reject": None,
    "reason": "default: keep the H4 engine",
}


def product_has_shop_channel(item):
    """True if any town shop type ever buys this product. Melon is False."""
    return any(item in products for products in SHOPS.values())


def tile_census(tiles):
    """Public-tile counts. Does not read the shed (hidden for the opponent)."""
    animals, crops = {}, {}
    empty = locked = weeds = owned = 0
    for row in tiles or []:
        for tile in row:
            if tile == "LOCKED":
                locked += 1
                continue
            owned += 1
            if tile is None:
                empty += 1
                continue
            if not isinstance(tile, dict):
                empty += 1
                continue
            if tile.get("animal"):
                animals[tile["animal"]] = animals.get(tile["animal"], 0) + 1
            elif tile.get("crop"):
                crops[tile["crop"]] = crops.get(tile["crop"], 0) + 1
            elif tile.get("kind") == "WEED":
                weeds += 1
            else:
                empty += 1
    productive = sum(animals.values()) + sum(crops.values())
    return {
        "owned": owned,
        "empty": empty,
        "locked": locked,
        "weeds": weeds,
        "animals": animals,
        "crops": crops,
        "n_animals": sum(animals.values()),
        "n_plants": sum(crops.values()),
        "wheat": crops.get("WHEAT", 0),
        "fill": productive / max(1, owned),
    }


def one_time_crop_units(crop, plant_day, last_day):
    """Unfertilized one-time yield if planted on `plant_day`.

    Engine: bonus window starts at ceil(max_yield_day/2) as crop age; each
    watered day in the window adds 1. Probe + table: wheat 4, carrot 3,
    melon 6, which matches 1 base unit (first_yield reached) plus window days,
    capped at max_yield. Returns 0 if first_yield cannot happen.
    """
    spec = CROPS[crop]
    first, maxd, cap = spec["first_yield_day"], spec["max_yield_day"], spec["max_yield"]
    if plant_day + first > last_day:
        return 0
    last_age = min(maxd, last_day - plant_day)
    window_start = (maxd + 1) // 2
    bonus_days = max(0, last_age - window_start + 1)
    return min(cap, 1 + bonus_days)


def ongoing_crop_events(crop, plant_day, from_day, last_day):
    """Remaining scheduled productions for an ongoing crop already in the ground.

    Tomato ages 8–11 (interval 1); strawberry 10,12,14,16 (interval 2).
    Cap is max_yield scheduled events, then the plant decays.
    """
    spec = CROPS[crop]
    first, interval, cap = spec["first_yield_day"], spec["interval"], spec["max_yield"]
    produced = n = 0
    for d in range(plant_day, last_day + 1):
        age = d - plant_day
        if age < first or (age - first) % interval != 0:
            continue
        if produced >= cap:
            break
        produced += 1
        if d >= from_day:
            n += 1
    return n


def remaining_yield_events(animal, placed_day, from_day, last_day):
    spec = ANIMALS[animal]
    first, interval = spec["first_yield_day"], spec["interval"]
    n = 0
    for day in range(from_day, last_day + 1):
        days_since_first = (day + 1) - placed_day - first
        if days_since_first >= 0 and days_since_first % interval == 0:
            n += 1
    return n


def remaining_wheat_cycles(day, last_day):
    """How many wheat plant→harvest cycles still fit."""
    n = 0
    d = day
    first = CROPS["WHEAT"]["first_yield_day"]
    span = CROPS["WHEAT"]["max_yield_day"] + 1
    while d + first <= last_day:
        n += 1
        d += span
        if n > 20:
            break
    return n


def wheat_tile_ev(day, last_day, prices, inventory, shops):
    """Realizable remaining value of one wheat tile kept on the H4 loop."""
    cycles = remaining_wheat_cycles(day, last_day)
    units = cycles * one_time_crop_units("WHEAT", day, last_day)
    seed = cycles * CROPS["WHEAT"]["seed"]
    exp, _ = walked_revenue("WHEAT", units, inventory, shops, day, last_day, 0)
    return exp - seed


def walked_revenue(item, qty, inventory, shops, day, last_day, opp_qty,
                   floor_fraction=0.30):
    """Sell `qty` after `opp_qty` competing units, capped by remaining absorption.

    Absorption = units until price < floor_fraction of base + expected remaining
    town drain (same construction as livestock_cap). Opponent shed is not
    visible; opp_qty should be visible remaining tile output only.
    """
    qty = max(0, int(qty))
    opp_qty = max(0, int(opp_qty))
    inv = inventory if inventory is not None else MARKET_I0
    room = units_until_price(item, inv, floor_fraction)
    town = expected_remaining_demand(
        item, day, shops or [], season_days=last_day + 1)
    absorb = max(0, int(room + town))
    opp_sold = min(opp_qty, absorb)
    if opp_sold:
        _, inv = sell_revenue(item, opp_sold, inv)
    ours = min(qty, max(0, absorb - opp_sold))
    if ours <= 0:
        return 0.0, 0
    rev, _ = sell_revenue(item, ours, inv)
    return float(rev), ours


def visible_remaining_units(tiles, day, last_day, product, care=False):
    """Tile output still to come for `product`. Shed is hidden.

    `care=True` counts H4-style CARE as 1+interval units per remaining
    livestock event. Opponent care is not observed; the conservative path
    leaves this False for competing supply.
    """
    units = 0
    for row in tiles or []:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            animal = tile.get("animal")
            if animal and ANIMAL_PRODUCT.get(animal) == product:
                units += tile.get("yield_units", 0) or 0
                events = remaining_yield_events(
                    animal, tile.get("placed_day", day), day, last_day)
                per = (1 + ANIMALS[animal]["interval"]) if care else 1
                units += events * per
                continue
            crop = tile.get("crop")
            if not crop or CROP_PRODUCT.get(crop) != product:
                continue
            held = tile.get("yield_units", 0) or 0
            planted = tile.get("planted_day", day)
            spec = CROPS[crop]
            if spec["ongoing"]:
                units += held + ongoing_crop_events(crop, planted, day, last_day)
            else:
                age = day - planted
                if age >= spec["first_yield_day"]:
                    units += held
                else:
                    units += one_time_crop_units(crop, planted, last_day)
    return units


def _premium_shock(item):
    """Extra competing units on the conservative path for delayed premium goods.

    No shop sells melon; strawberry/wool/milk crash above I0. When the
    opponent currently shows zero of that product, expected==conservative
    would treat today's empty market as a guarantee 10 days from now.
    Shock = T/6 is a modest glut before harvest, not a replay special case.
    """
    p = MARKET_PARAMS.get(item) or {}
    if p.get("above_target", 0) <= 1.0:
        return 0
    return max(0, int(p["T"] // 6))


def snapshot_from_obs(obs, player=None):
    """Build the evaluate_opportunities snapshot from a turn observation."""
    player = obs["player"] if player is None else player
    farms = obs.get("farms") or []
    farm = farms[player]
    opp = farms[1 - player] if len(farms) > 1 else None
    market = obs.get("market") or {}
    own_shed = {}
    if player == obs.get("player"):
        own_shed = dict((obs.get("private") or {}).get("shed") or {})
    return {
        "day": obs.get("day", 0),
        "last_day": 29,
        "money": farm.get("money", 0),
        "prices": dict(market.get("prices") or {}),
        "inventory": dict(market.get("inventory") or {}),
        "shops": list((obs.get("town") or {}).get("unlocked_shops") or []),
        "n_quads": len(farm.get("unlocked_quadrants") or []),
        "own_tiles": farm.get("tiles"),
        "own_shed": own_shed,
        "opp_tiles": (opp or {}).get("tiles") if opp else None,
        "opp_money": (opp or {}).get("money") if opp else None,
        "opp_quads": len((opp or {}).get("unlocked_quadrants") or []) if opp else 1,
    }


def _units_for_new_animal(animal, day, last_day, n, care):
    first = ANIMALS[animal]["first_yield_day"]
    if day + first > last_day:
        return 0
    events = remaining_yield_events(animal, day, day + 1, last_day)
    per = (1 + ANIMALS[animal]["interval"]) if care else 1
    return events * per * n


def _units_for_new_sheep(day, last_day, n, care):
    return _units_for_new_animal("SHEEP", day, last_day, n, care)


def _package(pid, **kw):
    row = dict(STAY)
    row.update(kw)
    row["id"] = pid
    return row


def evaluate_opportunities(snap, min_npv=0, min_expected=0, floor_fraction=0.30,
                           livestock_reserve=300, land_reserve=500):
    """Rank packages against STAY_H4. Never mutates agent state."""
    day = int(snap.get("day", 0))
    last_day = int(snap.get("last_day", 29))
    money = float(snap.get("money") or 0)
    prices = snap.get("prices") or {}
    inventory = snap.get("inventory") or {}
    shops = snap.get("shops") or []
    n_quads = int(snap.get("n_quads") or 1)
    own = snap.get("own_tiles")
    opp = snap.get("opp_tiles")
    wheat_q = prices.get("WHEAT") or MARKET_PARAMS["WHEAT"]["base"]

    def inv(item):
        return inventory.get(item, MARKET_I0)

    def opp_units(product):
        return visible_remaining_units(opp, day, last_day, product)

    def revenue(item, qty, conservative):
        competing = opp_units(item) if conservative else 0
        if conservative:
            competing += _premium_shock(item)
        rev, sold = walked_revenue(
            item, qty, inv(item), shops, day, last_day, competing, floor_fraction)
        return rev, sold

    def wheat_cost_of_feed(n_animals, days):
        return n_animals * days * wheat_q

    days_left = max(0, last_day - day + 1)
    land_price = LAND_PRICES[0] if n_quads <= 1 else 0
    already_expanded = n_quads > 1

    wheat_tile = wheat_tile_ev(day, last_day, prices, inv("WHEAT"), shops)
    census = tile_census(own)
    wheat_n = census["wheat"]
    empty_n = census["empty"]

    packages = [dict(STAY)]

    def add_livestock_package(pid, label, animal, n, use_land, displace_n=0, empty=False):
        spec = ANIMALS[animal]
        product = spec["product"]
        first = spec["first_yield_day"]
        latest = last_day - first
        land = land_price if use_land and not already_expanded else 0
        cost = land + n * spec["cost"]
        exp_u = _units_for_new_animal(animal, day, last_day, n, care=True)
        con_u = _units_for_new_animal(animal, day, last_day, n, care=False)
        exp_r, _ = revenue(product, exp_u, False)
        con_r, _ = revenue(product, con_u, True)
        feed = wheat_cost_of_feed(n, days_left)
        tile_cost = wheat_tile * displace_n
        reject = None
        if day > latest:
            reject = "cannot_mature"
        if use_land and already_expanded:
            reject = reject or "already_have_land"
        if not use_land and not empty and n_quads <= 1 and displace_n <= 0:
            reject = reject or "no_spare_pasture"
        if displace_n and wheat_n < displace_n:
            reject = reject or "no_wheat_to_displace"
        if empty and empty_n < n:
            reject = reject or "no_empty_tile"
        bonus = {"sheep_bonus": 0, "cow_bonus": 0}
        if animal == "SHEEP":
            bonus["sheep_bonus"] = n
        elif animal == "COW":
            bonus["cow_bonus"] = n
        engine = "keeps NW wheat; extra feed on new land" if use_land else (
            "uses empty tile; wheat engine intact" if empty else
            "displaces wheat; cuts feed surplus")
        npv_c = con_r - cost - feed - tile_cost
        risk = 1.0 if reject == "cannot_mature" else (0.0 if npv_c > 0 else 0.6)
        packages.append(_package(
            pid, label=label, cost=cost, land_cost=land,
            expected_npv=exp_r - cost - feed - tile_cost,
            conservative_npv=npv_c,
            latest_day=latest, earliest_payoff_day=day + first,
            buy_land=1 if (use_land and not already_expanded) else 0,
            displace_n=displace_n, pin=bool(use_land or empty),
            expected_yield_units=exp_u, conservative_revenue=con_r,
            feed_cost=feed, tile_opportunity_cost=tile_cost, labor_cost=0.0,
            engine_effect=engine, payback_risk=risk,
            reject=reject, reason=label, **bonus,
        ))

    def add_crop_package(pid, label, crop, n_tiles, use_land, displace=False):
        spec = CROPS[crop]
        latest = last_day - spec["first_yield_day"]
        land = land_price if use_land and not already_expanded else 0
        seed = n_tiles * spec["seed"]
        cost = land + seed
        if spec["ongoing"]:
            units_each = ongoing_crop_events(
                crop, day, day + spec["first_yield_day"], last_day)
        else:
            units_each = one_time_crop_units(crop, day, last_day)
        qty = units_each * n_tiles
        exp_r, _ = revenue(crop, qty, False)
        con_r, _ = revenue(crop, qty, True)
        tile_cost = wheat_tile * n_tiles if displace else 0.0
        reject = None
        if day > latest:
            reject = "cannot_mature"
        if use_land and already_expanded:
            reject = reject or "already_have_land"
        if not product_has_shop_channel(crop):
            reject = reject or "no_shop_demand"
        if displace and wheat_n < n_tiles:
            reject = reject or "no_wheat_to_displace"
        tpu = 3.3 if use_land else None
        engine = ("keeps NW wheat; premium on new land" if use_land else
                  "displaces wheat; cuts feed surplus")
        npv_c = con_r - cost - tile_cost
        risk = 1.0 if reject in ("cannot_mature", "no_shop_demand") else (
            0.0 if npv_c > 0 else 0.6)
        packages.append(_package(
            pid, label=label, cost=cost, land_cost=land,
            expected_npv=exp_r - cost - tile_cost,
            conservative_npv=npv_c,
            latest_day=latest,
            earliest_payoff_day=day + spec["first_yield_day"],
            extra_crop=crop if use_land else "",
            buy_land=1 if (use_land and not already_expanded) else 0,
            displace_crop=crop if displace else "",
            displace_n=n_tiles if displace else 0,
            tiles_per_unit=tpu, pin=bool(use_land or displace),
            crop_tiles=n_tiles,
            expected_yield_units=qty, conservative_revenue=con_r,
            feed_cost=0.0, tile_opportunity_cost=tile_cost, labor_cost=0.0,
            engine_effect=engine, payback_risk=risk, reject=reject,
            reason=label,
        ))

    add_livestock_package("LAND_SHEEP_1", "land + 1 sheep", "SHEEP", 1, True)
    add_livestock_package("LAND_SHEEP_3", "land + 3 sheep", "SHEEP", 3, True)
    add_livestock_package("LAND_COW_3", "land + 3 cows", "COW", 3, True)
    add_livestock_package("SHEEP_1_DISPLACE", "1 sheep on a wheat tile",
                          "SHEEP", 1, False, displace_n=1)
    add_livestock_package("COW_1_DISPLACE", "1 cow on a wheat tile",
                          "COW", 1, False, displace_n=1)
    if empty_n >= 1:
        add_livestock_package("SHEEP_1_EMPTY", "1 sheep on an empty tile",
                              "SHEEP", 1, False, empty=True)
        add_livestock_package("COW_1_EMPTY", "1 cow on an empty tile",
                              "COW", 1, False, empty=True)
    add_crop_package("LAND_STRAWBERRY_4", "land + 4 strawberry", "STRAWBERRY", 4, True)
    add_crop_package("LAND_TOMATO_4", "land + 4 tomato", "TOMATO", 4, True)
    add_crop_package("LAND_MELON_4", "land + 4 melon", "MELON", 4, True)
    add_crop_package("STRAW_4_DISPLACE", "4 strawberry replacing wheat",
                     "STRAWBERRY", 4, False, True)
    add_crop_package("MELON_4_DISPLACE", "4 melon replacing wheat",
                     "MELON", 4, False, True)

    ranked = []
    for p in packages:
        if p["id"] != "STAY_H4":
            need = p["cost"] + livestock_reserve + (land_reserve if p["land_cost"] else 0)
            if p["reject"] is None and need > money:
                p = dict(p)
                p["reject"] = "insufficient_cash"
            if p["reject"] is None and p["conservative_npv"] < min_npv:
                p = dict(p)
                p["reject"] = "conservative_below_floor"
            if p["reject"] is None and p["expected_npv"] < min_expected:
                p = dict(p)
                p["reject"] = "expected_below_floor"
        ranked.append(p)
    stay = [p for p in ranked if p["id"] == "STAY_H4"]
    rest = [p for p in ranked if p["id"] != "STAY_H4"]
    rest.sort(key=lambda p: (p["conservative_npv"], p["expected_npv"]), reverse=True)
    return stay + rest


def select_opportunity(ranked):
    """Best non-rejected package, else STAY_H4. Ties keep H4."""
    stay = ranked[0] if ranked and ranked[0]["id"] == "STAY_H4" else dict(STAY)
    viable = [p for p in ranked if p["id"] != "STAY_H4" and not p.get("reject")]
    if not viable:
        return stay
    best = viable[0]
    if best["conservative_npv"] <= 0:
        return stay
    return best
