"""Candidate elite production engine: state → economic choice.

Research only. The H4 executor does not import this module. Nothing here is
a day-index, opponent name, or a copied Crop Dusta / Ryo action sequence.

Every decision is a function of observable state:

    fill, empty tiles, cash, remaining days, shops, quotes/inventory,
    own/opponent visible output, occupancy, animals, shed wheat/fertilizer.

The intended objective is:

    maximize remaining earning capacity subject to feed, labor, absorption,
    and maturity — not maximize current cash.

Call `evaluate_engine(obs)` to ask what this policy would choose at a turn.
"""

import functools
import math

from .market import MARKET_I0, expected_remaining_demand, units_until_price
from .opportunity import (
    one_time_crop_units, ongoing_crop_events, remaining_yield_events,
    snapshot_from_obs, tile_census, visible_remaining_units, walked_revenue,
)
from .tables import (
    ANIMALS, CROPS, LAND_PRICES, MARKET_PARAMS, SHOPS, cumulative_hire_cost,
)

FLOOR = 0.30
LAST_DAY = 29
# 24 actions × ~0.5 travel leftover × ~2 ops/tile (water+feed/care) ≈ 6 tiles.
TILES_PER_HAND = 6
MAX_HANDS = 12
FEED_RESERVE = 2
MIN_CASH_RESERVE = 0  # elites buy land/animals down to a few hundred dollars
WHEAT_PER_TILE_PER_DAY = 0.8  # 4 unfertilized units / 5-day cycle


def _shock(item):
    p = MARKET_PARAMS.get(item) or {}
    if p.get("above_target", 0) <= 1.0:
        return 0
    return max(0, int(p["T"] // 6))


def _apply_pending(own, pending):
    """Count in-turn planned plants so one hour does not over-allocate melon."""
    if not pending:
        return own
    crops = dict(own["crops"])
    add = 0
    for crop, n in pending.items():
        n = int(n)
        if n <= 0:
            continue
        crops[crop] = crops.get(crop, 0) + n
        add += n
    own = dict(own)
    own["crops"] = crops
    own["n_plants"] = own["n_plants"] + add
    own["empty"] = max(0, own["empty"] - add)
    own["wheat"] = crops.get("WHEAT", 0)
    own["fill"] = (own["n_animals"] + own["n_plants"]) / max(1, own["owned"])
    return own


def _census_both(snap):
    own = tile_census(snap.get("own_tiles"))
    opp = tile_census(snap.get("opp_tiles"))
    own = _apply_pending(own, snap.get("pending_crops") or {})
    return own, opp


def _days_left(snap):
    return max(0, int(snap.get("last_day", LAST_DAY)) - int(snap.get("day", 0)) + 1)


def _inv(snap, item):
    return (snap.get("inventory") or {}).get(item, MARKET_I0)


def _shops(snap):
    return list(snap.get("shops") or [])


def conservative_sold_revenue(snap, item, qty):
    """Walked revenue after opponent visible units and a premium glut shock."""
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    opp = visible_remaining_units(snap.get("opp_tiles"), day, last, item)
    rev, sold = walked_revenue(
        item, qty, _inv(snap, item), _shops(snap), day, last,
        opp + _shock(item), FLOOR)
    return rev, sold


def expected_sold_revenue(snap, item, qty):
    """Walked revenue with no opponent and no glut shock.

    Used only as a diagnostic against conservative NPV. Ranking and
    accept/reject stay conservative so we do not globally loosen floors.
    """
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    rev, sold = walked_revenue(
        item, qty, _inv(snap, item), _shops(snap), day, last, 0, FLOOR)
    return rev, sold


@functools.lru_cache(maxsize=8192)
def _cached_until(item, inventory, floor):
    return units_until_price(item, inventory, floor)


@functools.lru_cache(maxsize=8192)
def _cached_town(item, day, shops, season_days):
    return expected_remaining_demand(item, day, list(shops), season_days=season_days)


def remaining_absorption(snap, item):
    """Units still sellable above FLOOR × base, after opponent + shock + town."""
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    inv = int(_inv(snap, item))
    room = _cached_until(item, inv, FLOOR)
    town = _cached_town(item, day, tuple(_shops(snap)), last + 1)
    opp = visible_remaining_units(snap.get("opp_tiles"), day, last, item)
    return max(0, int(room + town) - opp - _shock(item))


def wheat_quote(snap):
    return float((snap.get("prices") or {}).get("WHEAT")
                 or MARKET_PARAMS["WHEAT"]["base"])


def feed_cost(snap, n_animals, days):
    return n_animals * max(0, days) * wheat_quote(snap)


def melon_policy_of(snap):
    """Research ablation knob. Missing/None/pa/conservative = E77 default.

    Not a day-index. `all` ignores absorption but still requires maturity
    and empty tiles. An int is a state occupancy cap, not a calendar batch.
    """
    p = snap.get("melon_policy")
    if p is None or p == "" or p == "pa" or p == "conservative":
        return "conservative", None
    if p == "all" or p == -1:
        return "all", None
    return "cap", int(p)


def melon_justified_tiles(snap):
    """Remaining melon tiles to add this hour. Zero if it cannot mature.

    Default (no melon_policy): conservative absorption / 6 minus current
    occupancy (including in-turn pending). Ablation policies replace the
    absorption term with a configured cap or with mechanical empty tiles.
    """
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    if day + CROPS["MELON"]["first_yield_day"] > last:
        return 0, "cannot_mature"
    own, _ = _census_both(snap)
    own_melon = own["crops"].get("MELON", 0)
    empty = own["empty"]
    kind, cap = melon_policy_of(snap)
    if empty <= 0:
        return 0, "no_empty_tile"
    if kind == "all":
        return empty, "all_viable"
    if kind == "cap":
        room = max(0, cap - own_melon)
        if room <= 0:
            return 0, "configured_cap"
        return min(room, empty), "configured_cap"
    # E77 conservative: board occupancy only (pending is applied by the
    # caller via own_melon < just). Do not fold pending into leftover here.
    board = tile_census(snap.get("own_tiles"))["crops"].get("MELON", 0)
    absorb = remaining_absorption(snap, "MELON")
    leftover_units = absorb - board * 6
    tiles = max(0, leftover_units // 6)
    return tiles, "absorption_over_yield"


def tile_npv(snap, use):
    """Conservative NPV of putting one more tile on `use` today."""
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    days = _days_left(snap)
    own, _ = _census_both(snap)

    if use == "EMPTY":
        return {"use": use, "npv": 0.0, "revenue": 0.0, "cost": 0.0,
                "expected_npv": 0.0, "expected_revenue": 0.0,
                "reject": None, "reason": "idle"}

    if use == "WHEAT":
        units = one_time_crop_units("WHEAT", day, last)
        if units <= 0:
            return _rej(use, "cannot_mature")
        rev, sold = conservative_sold_revenue(snap, "WHEAT", units)
        cost = CROPS["WHEAT"]["seed"]
        return _ok(snap, "WHEAT", units, use, rev - cost, rev, cost, f"sold={sold}")

    if use == "MELON":
        just, why = melon_justified_tiles(snap)
        units = one_time_crop_units("MELON", day, last)
        if just <= 0:
            return _rej(use, why, snap, "MELON", units, CROPS["MELON"]["seed"])
        if units <= 0:
            return _rej(use, "cannot_mature")
        rev, sold = conservative_sold_revenue(snap, "MELON", units)
        cost = CROPS["MELON"]["seed"]
        return _ok(snap, "MELON", units, use, rev - cost, rev, cost,
                   f"justified={just} sold={sold}")

    if use == "STRAWBERRY":
        events = ongoing_crop_events("STRAWBERRY", day, day, last)
        cost = CROPS["STRAWBERRY"]["seed"]
        if events <= 0:
            return _rej(use, "cannot_mature", snap, "STRAWBERRY", 0, cost)
        # Unfertilized 1/event; fertilizer is a separate decision.
        rev, sold = conservative_sold_revenue(snap, "STRAWBERRY", events)
        return _ok(snap, "STRAWBERRY", events, use, rev - cost, rev, cost,
                   f"events={events} sold={sold}")

    if use == "CARROT":
        cost = CROPS["CARROT"]["seed"]
        if "PET_CAFE" not in _shops(snap) and "FARMERS_MARKET" not in _shops(snap):
            return _rej(use, "no_shop_channel")
        units = one_time_crop_units("CARROT", day, last)
        if units <= 0:
            return _rej(use, "cannot_mature")
        rev, sold = conservative_sold_revenue(snap, "CARROT", units)
        return _ok(snap, "CARROT", units, use, rev - cost, rev, cost, f"sold={sold}")

    if use in ANIMALS:
        spec = ANIMALS[use]
        product = spec["product"]
        first = spec["first_yield_day"]
        if day + first > last:
            return _rej(use, "cannot_mature")
        events = remaining_yield_events(use, day, day + 1, last)
        if events <= 0:
            return _rej(use, "no_events")
        # Conservative: 1 unit/event (no CARE assumption).
        rev, sold = conservative_sold_revenue(snap, product, events)
        cost = spec["cost"] + feed_cost(snap, 1, days)
        return _ok(snap, product, events, use, rev - cost, rev, cost,
                   f"events={events} sold={sold} product={product}")

    return _rej(use, "unknown")


def _ok(snap, item, units, use, npv, rev, cost, reason):
    erev, esold = expected_sold_revenue(snap, item, units)
    return {
        "use": use, "npv": float(npv), "revenue": float(rev),
        "cost": float(cost), "reject": None, "reason": reason,
        "expected_npv": float(erev - cost), "expected_revenue": float(erev),
        "expected_sold": int(esold),
        "velocity_gap": False,
        "absorption": remaining_absorption(snap, item),
    }


def _rej(use, why, snap=None, item=None, units=0, cost=0):
    row = {"use": use, "npv": 0.0, "revenue": 0.0, "cost": float(cost),
           "expected_npv": 0.0, "expected_revenue": 0.0, "expected_sold": 0,
           "reject": why, "reason": why, "velocity_gap": False,
           "absorption": 0}
    if snap is not None and item and units:
        erev, esold = expected_sold_revenue(snap, item, units)
        row["expected_npv"] = float(erev - cost)
        row["expected_revenue"] = float(erev)
        row["expected_sold"] = int(esold)
        row["absorption"] = remaining_absorption(snap, item)
        row["velocity_gap"] = row["expected_npv"] > 0
    return row


def feed_shortfall_tiles(snap):
    """Wheat tiles still needed so farm output covers animals after reserve.

    Elites also BUY_PRODUCT wheat; this is the *minimum occupancy* for feed
    so premium tiles are not starved. Surplus feed is bought, not grown,
    when premium NPV is higher.
    """
    own, _ = _census_both(snap)
    animals = own["n_animals"]
    wheat_tiles = own["crops"].get("WHEAT", 0)
    shed = (snap.get("own_shed") or {}).get("WHEAT", 0)
    days = _days_left(snap)
    need = animals * days + animals * FEED_RESERVE
    have = shed + wheat_tiles * WHEAT_PER_TILE_PER_DAY * days
    gap = max(0.0, need - have)
    denom = WHEAT_PER_TILE_PER_DAY * max(1, days)
    return int(math.ceil(gap / denom)) if gap else 0


def choose_tile_use(snap, pending=None, crop_only=False):
    """Highest conservative NPV use for one empty unlocked tile.

    Wheat is an input. It wins only when feed would otherwise fail or when
    every premium use is rejected (glut / cannot mature).

    `crop_only` is the Phase A executor path: livestock stays on the frozen
    H4 layout; this function must not steal crop tiles for extra animals.
    """
    snap = dict(snap)
    if pending:
        merged = dict(snap.get("pending_crops") or {})
        for crop, n in pending.items():
            merged[crop] = merged.get(crop, 0) + int(n)
        snap["pending_crops"] = merged
    own, _ = _census_both(snap)
    uses = ("MELON", "STRAWBERRY", "CARROT", "WHEAT") if crop_only else (
        "MELON", "STRAWBERRY", "CARROT", "SHEEP", "COW", "GOOSE", "WHEAT")
    ranked = []
    for use in uses:
        row = tile_npv(snap, use)
        ranked.append(row)
    ranked.sort(key=lambda r: r["npv"], reverse=True)
    best = ranked[0] if ranked else _rej("EMPTY", "none")
    feed_need = feed_shortfall_tiles(snap)
    if feed_need > 0 and own["empty"] <= feed_need:
        money = float(snap.get("money") or 0)
        animals = own["n_animals"]
        if money < wheat_quote(snap) * max(1, animals):
            wheat = tile_npv(snap, "WHEAT")
            wheat = dict(wheat)
            wheat["reason"] = "feed_constraint:" + wheat["reason"]
            return wheat, ranked
    melon_row = next((r for r in ranked if r["use"] == "MELON"), None)
    straw_row = next((r for r in ranked if r["use"] == "STRAWBERRY"), None)
    just, just_why = melon_justified_tiles(snap)
    kind, _ = melon_policy_of(snap)
    fallback = snap.get("melon_fallback") or "pa"
    own_melon = own["crops"].get("MELON", 0)
    # Opener then fill: myopic 1-tile melon NPV stays high and would replant
    # into a glut. Conservative E77: occupancy < absorption/6. Ablation:
    # remaining-justified > 0 even if conservative 1-tile NPV collapsed.
    want_melon = False
    if kind == "conservative":
        want_melon = (own_melon < just and just > 0 and melon_row
                      and melon_row.get("npv", 0) > 0
                      and melon_row.get("reject") is None)
    elif just > 0 and melon_row and melon_row.get("reject") != "cannot_mature":
        want_melon = True
    if want_melon:
        if melon_row.get("reject") is None:
            return melon_row, ranked
        units = one_time_crop_units(
            "MELON", int(snap.get("day", 0)),
            int(snap.get("last_day", LAST_DAY)))
        if units > 0:
            row = dict(melon_row)
            row["reject"] = None
            row["reason"] = just_why
            return row, ranked
    if fallback == "wheat_feed":
        wheat = tile_npv(snap, "WHEAT")
        if wheat["npv"] > 0:
            wheat = dict(wheat)
            if just > 0:
                wheat["melon_skip"] = wheat["reason"]
            return wheat, ranked
        empty = _rej("EMPTY", "no_positive_use")
        if just > 0:
            empty["melon_skip"] = "no_positive_use"
        return empty, ranked
    if straw_row and straw_row["npv"] > 0 and straw_row["reject"] is None:
        straw = dict(straw_row)
        if just > 0:
            straw["melon_skip"] = just_why
        return straw, ranked
    if best["npv"] <= 0 or best["reject"]:
        wheat = tile_npv(snap, "WHEAT")
        if wheat["npv"] > 0:
            return wheat, ranked
        return _rej("EMPTY", "no_positive_use"), ranked
    return best, ranked


def labor_target(snap):
    """Hands scale with owned tiles. Not a 4/8/12 script.

    owned=25 → 4, 50 → 8, 75 → 12, 100 → 12 (cap). The cap is economic:
    fib(12)=233 for the 13th hand, and 12 hands already cover a 75-tile
    fill at ~6 tiles/hand. Dawn cash does not shrink the target; elites
    hire as sales arrive.
    """
    own, _ = _census_both(snap)
    owned = max(1, own["owned"])
    raw = max(0, owned // TILES_PER_HAND)
    target = min(MAX_HANDS, raw)
    money = float(snap.get("money") or 0)
    cost = cumulative_hire_cost(target)
    reserve = own["n_animals"] * wheat_quote(snap) * FEED_RESERVE
    # Target is occupancy-driven. Dawn cash often sits near zero because
    # elites hire as sales arrive; do not shrink the target to dawn cash.
    return {
        "hands": target,
        "owned": owned,
        "cost": cost,
        "reserve": reserve,
        "affordable_now": cost + reserve <= money + 1e-9,
        "reason": f"owned//{TILES_PER_HAND} cap={MAX_HANDS}",
    }


def land_decision(snap):
    """Buy the next quadrant iff current farm is saturated AND new tiles pay.

    Not 'buy when full'. Saturation is necessary. Sufficiency is conservative
    NPV of the best use × 25 minus land price, with a maturity gate and a
    labor-cover check. The fourth quadrant is not banned; it fails when
    extra strawberry/livestock would sell into a glut.
    """
    own, _ = _census_both(snap)
    n_quads = int(snap.get("n_quads") or 1)
    money = float(snap.get("money") or 0)
    days = _days_left(snap)
    if n_quads >= 4:
        return {"buy": False, "reason": "all_unlocked", "npv": 0.0,
                "fill": own["fill"], "price": 0}
    price = LAND_PRICES[n_quads - 1] if n_quads >= 1 else LAND_PRICES[0]
    fill = own["fill"]
    empty = own["empty"] + own["weeds"]
    unripe_melon = own["crops"].get("MELON", 0)
    # Melon locks tiles until harvest. Expand when those tiles leave too
    # little rotatable space for the fill crop — not only at fill>=0.90.
    cannot_rotate_opener = unripe_melon > 0 and empty < unripe_melon
    if fill < 0.90 and empty > 2 and not cannot_rotate_opener:
        return {"buy": False, "reason": "not_saturated", "npv": 0.0,
                "fill": fill, "price": price, "empty": empty}
    if money < price + MIN_CASH_RESERVE:
        return {"buy": False, "reason": "cannot_afford", "npv": 0.0,
                "fill": fill, "price": price, "money": money}
    # Hypothetical 25 extra empty tiles: reuse choose_tile_use on a copy
    # that pretends we already own them (fill drops, empty rises).
    extra_owned = own["owned"] + 25
    coverable = MAX_HANDS * TILES_PER_HAND
    slack = coverable - own["owned"]
    if slack <= 0:
        return {"buy": False, "reason": "labor_cannot_cover", "npv": 0.0,
                "fill": fill, "price": price, "coverable": coverable,
                "owned": own["owned"]}
    labor = labor_target({**snap, "n_quads": n_quads + 1})
    # Labor target uses owned from tiles; approximate with extra_owned.
    labor_hands = min(MAX_HANDS, extra_owned // TILES_PER_HAND)
    labor_cost = cumulative_hire_cost(labor_hands) - cumulative_hire_cost(
        labor["hands"])
    best, ranked = choose_tile_use(snap)
    # Value the 25 new tiles at the current best use, but cap by remaining
    # absorption so a second wave of melon/strawberry is not 25× the 1-tile NPV.
    use = best["use"]
    if best["npv"] <= 0 or best["reject"]:
        return {"buy": False, "reason": "no_profitable_use", "npv": 0.0,
                "fill": fill, "price": price, "best": best}
    if use == "MELON":
        just, _ = melon_justified_tiles(snap)
        n = min(25, slack, just)
    elif use in ANIMALS:
        absorb = remaining_absorption(snap, ANIMALS[use]["product"])
        events = remaining_yield_events(
            use, int(snap.get("day", 0)), int(snap.get("day", 0)) + 1,
            int(snap.get("last_day", LAST_DAY)))
        n = min(25, slack, absorb // max(1, events)) if events else 0
    elif use in CROPS:
        absorb = remaining_absorption(snap, use)
        per = (one_time_crop_units(use, int(snap.get("day", 0)),
                                   int(snap.get("last_day", LAST_DAY)))
               if not CROPS[use]["ongoing"] else
               ongoing_crop_events(use, int(snap.get("day", 0)),
                                   int(snap.get("day", 0)),
                                   int(snap.get("last_day", LAST_DAY))))
        n = min(25, slack, absorb // max(1, per)) if per else 0
    else:
        n = 0
    gross = best["npv"] * n - labor_cost
    npv = gross - price
    mature_ok = days >= 6  # sheep first_yield; strawberry needs 10, checked in use
    if use == "STRAWBERRY" and days < CROPS["STRAWBERRY"]["first_yield_day"]:
        mature_ok = False
    if use == "MELON" and days < CROPS["MELON"]["first_yield_day"]:
        mature_ok = False
    if not mature_ok:
        return {"buy": False, "reason": "cannot_mature_use", "npv": npv,
                "fill": fill, "price": price, "best": best, "n": n}
    if npv <= 0:
        return {"buy": False, "reason": "npv_not_positive", "npv": npv,
                "fill": fill, "price": price, "best": best, "n": n}
    return {"buy": True, "reason": "saturated_and_npv", "npv": npv,
            "fill": fill, "price": price, "best": best, "n": n,
            "labor_delta": labor_cost}


FROZEN_HANDS = 6  # E79 isolation. labor_target() still scales; this does not.


def _valued_new_crop_tiles(snap, best):
    """How many of the next 25 tiles conservative NPV can fill. No labor cap."""
    use = best.get("use")
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    if use == "MELON":
        just, _ = melon_justified_tiles(snap)
        return min(25, max(0, just))
    if use in CROPS:
        absorb = remaining_absorption(snap, use)
        if CROPS[use]["ongoing"]:
            per = ongoing_crop_events(use, day, day, last)
        else:
            per = one_time_crop_units(use, day, last)
        if per <= 0:
            return 0
        return min(25, absorb // per)
    return 0


def _land_m18_result(buy, reason, **fields):
    row = {
        "buy": bool(buy),
        "reason": reason,
        "npv": 0.0,
        "npv_before_labor": 0.0,
        "npv_after_labor": 0.0,
        "executable_npv": 0.0,
        "labor_shortfall": 0,
        "coverable": 0,
        "owned": 0,
        "n_before": 0,
        "n_after": 0,
        "fill": 0.0,
        "price": 0,
        "empty": 0,
        "unripe_melon": 0,
        "money": 0.0,
        "best": None,
        "mode": None,
        "max_quads": None,
        "frozen_hands": FROZEN_HANDS,
    }
    row.update(fields)
    if "executable_npv" not in fields:
        row["executable_npv"] = float(row["npv_after_labor"] if buy else 0.0)
    if "npv" not in fields:
        row["npv"] = row["executable_npv"]
    return row


def land_decision_m18(snap, max_quads=2, mode="npv"):
    """E79 land gate: M18 occupancy + frozen six-hand labor.

    Does not mutate `snap`. No calendar. `land_decision()` is unchanged.

    NPV-before-labor values the new tiles at the current crop use (crop_only,
    so livestock stays 3+3). NPV-after-labor caps those tiles by
    (frozen_hands + farmer) × TILES_PER_HAND. SIMPLE still buys the next
    quadrant on saturation + cash + maturity even if after-labor NPV is
    negative, so idle tiles can be observed. NPV mode refuses when
    after-labor NPV is not positive.
    """
    snap = dict(snap)
    own, _ = _census_both(snap)
    n_quads = int(snap.get("n_quads") or 1)
    money = float(snap.get("money") or 0)
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    mode = (mode or "npv").lower()
    max_quads = int(max_quads)
    frozen_hands = int(snap.get("frozen_hands", FROZEN_HANDS))
    fill = own["fill"]
    empty = own["empty"] + own["weeds"]
    unripe_melon = own["crops"].get("MELON", 0)
    price = LAND_PRICES[n_quads - 1] if 1 <= n_quads < 4 else 0
    coverable = (frozen_hands + 1) * TILES_PER_HAND
    slack = coverable - own["owned"]
    labor_shortfall = max(0, own["owned"] + 25 - coverable)
    common = dict(fill=fill, price=price, empty=empty,
                  unripe_melon=unripe_melon, money=money,
                  owned=own["owned"], coverable=coverable,
                  labor_shortfall=labor_shortfall, mode=mode,
                  max_quads=max_quads, frozen_hands=frozen_hands)
    if n_quads >= 4:
        return _land_m18_result(False, "all_unlocked", **common)
    if n_quads >= max_quads:
        return _land_m18_result(False, "max_quads", **common)
    cannot_rotate_opener = unripe_melon > 0 and empty < unripe_melon
    # E79: extra land is a production-capacity lever, not a melon-lock
    # escape. Fill must actually be tight. The E76 cannot_rotate bypass
    # fired at fill~0.56 and bankrupted the six-hand farm.
    if fill < 0.90:
        return _land_m18_result(
            False, "not_saturated", cannot_rotate_opener=cannot_rotate_opener,
            **common)
    reserve = own["n_animals"] * wheat_quote(snap) * FEED_RESERVE
    if money < price + MIN_CASH_RESERVE + reserve:
        return _land_m18_result(
            False, "cannot_afford", cannot_rotate_opener=cannot_rotate_opener,
            **common)
    best, _ranked = choose_tile_use(snap, crop_only=True)
    n_before = _valued_new_crop_tiles(snap, best)
    n_after = min(n_before, max(0, slack))
    use = best.get("use")
    unit_npv = float(best.get("npv") or 0) if best and not best.get("reject") else 0.0
    npv_before = unit_npv * n_before - price
    npv_after = unit_npv * n_after - price
    common.update(best=best, n_before=n_before, n_after=n_after,
                  npv_before_labor=npv_before, npv_after_labor=npv_after)
    # New tiles are for M18 premium fill (strawberry after the global melon
    # cap), not wheat. Wheat-on-land is the H5A negative control. Gate on
    # remaining days vs strawberry/melon first yield, not a calendar index.
    premium_first = CROPS["STRAWBERRY"]["first_yield_day"]
    mature_ok = day + premium_first <= last
    if use == "MELON":
        mature_ok = day + CROPS["MELON"]["first_yield_day"] <= last
    elif use == "STRAWBERRY":
        mature_ok = day + CROPS["STRAWBERRY"]["first_yield_day"] <= last
    if not mature_ok:
        return _land_m18_result(False, "cannot_mature_use", **common)
    if mode != "simple" and slack <= 0:
        return _land_m18_result(False, "labor_cannot_cover", **common)
    if mode == "simple":
        return _land_m18_result(
            True, "saturated_allow", executable_npv=npv_after, **common)
    if unit_npv <= 0 or best.get("reject") or n_before <= 0:
        return _land_m18_result(False, "no_profitable_use", **common)
    if npv_after <= 0:
        return _land_m18_result(False, "npv_not_positive", **common)
    return _land_m18_result(
        True, "saturated_and_npv", executable_npv=npv_after, **common)


def livestock_targets(snap):
    """Absorption-capped targets. Not 13 sheep or 12 cows.

    Rank cow/sheep/goose by conservative NPV of one more animal. Buy while
    NPV > 0, pasture can be built or is empty, cash covers cost+feed reserve,
    and remaining events exist.
    """
    own, _ = _census_both(snap)
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    money = float(snap.get("money") or 0)
    empty_pasture = own.get("empty", 0)  # includes buildable empty tiles
    targets = {}
    buys = {}
    rows = []
    for animal in ("SHEEP", "COW", "GOOSE"):
        row = tile_npv(snap, animal)
        rows.append(row)
        have = own["animals"].get(animal, 0)
        if row["npv"] <= 0 or row["reject"]:
            targets[animal] = have
            buys[animal] = 0
            continue
        events = remaining_yield_events(animal, day, day + 1, last)
        absorb = remaining_absorption(snap, ANIMALS[animal]["product"])
        by_absorb = absorb // max(1, events) if events else 0
        # One new animal per evaluation step; the executor can re-ask.
        can_pay = money >= ANIMALS[animal]["cost"] + wheat_quote(snap) * FEED_RESERVE
        add = 1 if can_pay and empty_pasture > 0 and have < by_absorb else 0
        targets[animal] = have + add
        buys[animal] = add
    rows.sort(key=lambda r: r["npv"], reverse=True)
    # If two types both want +1, pick the higher NPV only.
    preferred = None
    for r in rows:
        if buys.get(r["use"], 0) > 0:
            preferred = r["use"]
            break
    if preferred:
        for a in list(buys):
            if a != preferred:
                buys[a] = 0
                targets[a] = own["animals"].get(a, 0)
    return {
        "targets": targets,
        "buy": buys,
        "ranked": rows,
        "reason": "max_conservative_npv_capped_by_absorption",
        "shops": _shops(snap),
    }


def fertilizer_decision(snap, crop=None):
    """Apply if extra yield × conservative price > fertilizer quote; else sell.

    Strawberry: fert+water doubles a scheduled event (+1 unit × up to 4).
    One-time crops: fert adds +1 unit/day in the bonus window, capped.
    Melon often already hits cap unfertilized; apply only if it creates
    earlier harvest (capital velocity) without wasting a unit that would
    exist anyway — treated as low priority vs strawberry.
    """
    prices = snap.get("prices") or {}
    fert_q = float(prices.get("FERTILIZER") or MARKET_PARAMS["FERTILIZER"]["base"])
    shed = snap.get("own_shed") or {}
    have = int(shed.get("FERTILIZER") or 0)
    if have <= 0:
        return {"apply": False, "sell": False, "reason": "none_in_shed",
                "crop": crop}

    def extra_rev(item, extra_units):
        rev, sold = conservative_sold_revenue(snap, item, extra_units)
        return rev, sold

    if crop == "STRAWBERRY":
        rev, sold = extra_rev("STRAWBERRY", 1)
        apply = sold > 0 and rev > fert_q
        return {"apply": apply, "sell": (not apply) and fert_q >= 1,
                "reason": f"berry_extra={rev:.0f} vs fert={fert_q:.0f}",
                "crop": crop}
    if crop in ("WHEAT", "CARROT"):
        rev, sold = extra_rev(crop, 2)  # +2 vs +1 per bonus day, ~window leftover
        apply = sold > 0 and rev > fert_q
        return {"apply": apply, "sell": not apply,
                "reason": f"{crop}_extra={rev:.0f} vs fert={fert_q:.0f}",
                "crop": crop}
    if crop == "MELON":
        # Unfertilized already reaches 6 at age 10. Fertilizer mainly
        # advances the harvest, not the unit count. Only apply if the
        # fertilizer quote has collapsed below a small velocity premium.
        apply = fert_q <= 20
        return {"apply": apply, "sell": not apply,
                "reason": f"melon_cap_already_6 fert_q={fert_q:.0f}",
                "crop": crop}
    return {"apply": False, "sell": True, "reason": "sell_commodity",
            "crop": crop}


def feed_decision(snap, animal, placed_day, yield_units=0):
    """Feed iff remaining events or unharvested product still exist.

    Not a calendar last-N-days rule. An animal whose next event is after
    last_day and whose tile is empty of product is not worth a wheat unit.
    """
    day = int(snap.get("day", 0))
    last = int(snap.get("last_day", LAST_DAY))
    if (yield_units or 0) > 0:
        return {"feed": True, "reason": "unharvested_on_tile"}
    if animal not in ANIMALS:
        return {"feed": False, "reason": "unknown_animal"}
    events = remaining_yield_events(animal, placed_day, day, last)
    if events <= 0:
        return {"feed": False, "reason": "no_remaining_events"}
    row = tile_npv(snap, animal)
    # Existing animal: feed cost is 1 wheat, not the purchase price.
    product = ANIMALS[animal]["product"]
    rev, sold = conservative_sold_revenue(snap, product, 1)
    wheat = wheat_quote(snap)
    if sold <= 0 or rev < wheat:
        return {"feed": False, "reason": "next_unit_below_feed_cost",
                "rev": rev, "wheat": wheat}
    return {"feed": True, "reason": "remaining_events_cover_feed",
            "events": events}


def sell_decision(snap, item, qty):
    """Sell unless holding is required for feed (wheat) or quote is collapsed
    AND remaining absorption is expected to recover (premium, shops).

    Terminal: remaining days 0 after this day → sell; unsold shed does not score.
    """
    days = _days_left(snap)
    own, _ = _census_both(snap)
    if item == "WHEAT":
        animals = own["n_animals"]
        keep = animals * FEED_RESERVE + animals  # today + buffer
        sell_qty = max(0, int(qty) - keep)
        return {"sell": sell_qty, "hold": keep, "reason": "feed_first"}
    if days <= 1:
        return {"sell": int(qty), "hold": 0, "reason": "terminal_convert"}
    quote = float((snap.get("prices") or {}).get(item) or 0)
    base = MARKET_PARAMS.get(item, {}).get("base", 1)
    if quote < FLOOR * base and remaining_absorption(snap, item) > int(qty):
        return {"sell": 0, "hold": int(qty),
                "reason": "quote_below_floor_absorption_remains"}
    return {"sell": int(qty), "hold": 0, "reason": "sell_at_quote"}


def evaluate_engine(obs, player=None):
    """Full policy vector for one observation. Does not mutate anything."""
    snap = snapshot_from_obs(obs, player)
    priv = obs.get("private") or {}
    if player is None or player == obs.get("player"):
        snap["own_shed"] = dict(priv.get("shed") or {})
        snap["seeds"] = dict(priv.get("seeds") or {})
    own, opp = _census_both(snap)
    snap_own = dict(snap)
    tile, ranked = choose_tile_use(snap_own)
    return {
        "day": snap["day"],
        "money": snap["money"],
        "n_quads": snap["n_quads"],
        "fill": own["fill"],
        "own": {k: own[k] for k in
                ("owned", "empty", "weeds", "n_animals", "n_plants",
                 "animals", "crops", "fill")},
        "opp_fill": opp["fill"],
        "shops": _shops(snap),
        "tile": tile,
        "tile_ranked": ranked,
        "labor": labor_target(snap_own),
        "land": land_decision(snap_own),
        "livestock": livestock_targets(snap_own),
        "fertilizer": fertilizer_decision(snap_own, crop=tile["use"]
                                          if tile["use"] in CROPS else None),
        "objective": "capacity_subject_to_feed_labor_absorption",
    }
