"""Ceiling detection, STAY_H4 terminal projection, stay-vs-convert.

Pure functions. The H4 executor never imports behaviour from here unless
`ceiling_convert_enabled` is on. Flag-off H4 is bit-for-bit unchanged.

This is not a calendar strategy. "Ceiling" is tile/livestock saturation plus
a remaining-output gap versus the visible opponent, not `day == 25`.
"""

from .opportunity import (STAY, evaluate_opportunities, product_has_shop_channel,
                          remaining_wheat_cycles, tile_census,
                          visible_remaining_units, walked_revenue)
from .tables import ANIMALS, CROPS, MARKET_I0, MARKET_PARAMS, PRODUCTS, cumulative_hire_cost


# Products whose remaining tile output can still move terminal cash.
OUTPUT_PRODUCTS = [p for p in PRODUCTS if p != "FERTILIZER"]

# Animals/crops the opportunity catalog actually offers as conversions.
CONVERT_ANIMALS = ("SHEEP", "COW")
CONVERT_CROPS = ("STRAWBERRY", "TOMATO")  # melon has no shop channel
H4_HANDS = 6


def days_left(day, last_day):
    return max(0, int(last_day) - int(day) + 1)


def remaining_hire_cost(day, last_day, n_hands=H4_HANDS):
    return days_left(day, last_day) * cumulative_hire_cost(n_hands)


def _inv(snap, item):
    inventory = snap.get("inventory") or {}
    return inventory.get(item, MARKET_I0)


def _units(tiles, day, last_day, product, care, shed=None):
    n = visible_remaining_units(tiles, day, last_day, product, care=care)
    if shed:
        n += int(shed.get(product, 0) or 0)
    return n


def split_remaining_revenue(snap, product, our_care, opp_care, floor_fraction=0.30):
    """Opponent visible units sell first, then ours. Independent per product."""
    day = int(snap.get("day", 0))
    last_day = int(snap.get("last_day", 29))
    shops = snap.get("shops") or []
    our = _units(snap.get("own_tiles"), day, last_day, product, our_care,
                 snap.get("own_shed") or {})
    opp = _units(snap.get("opp_tiles"), day, last_day, product, opp_care)
    our_rev, our_sold = walked_revenue(
        product, our, _inv(snap, product), shops, day, last_day, opp, floor_fraction)
    our_rev_sym, _ = walked_revenue(
        product, our, _inv(snap, product), shops, day, last_day, 0, floor_fraction)
    opp_rev, opp_sold = walked_revenue(
        product, opp, _inv(snap, product), shops, day, last_day, 0, floor_fraction)
    return {
        "product": product,
        "our_units": our,
        "opp_units": opp,
        "our_rev": float(our_rev),
        "our_rev_sym": float(our_rev_sym),
        "opp_rev": float(opp_rev),
        "our_sold": our_sold,
        "opp_sold": opp_sold,
    }


def net_wheat_cash(snap, floor_fraction=0.30):
    """Remaining wheat harvest minus remaining feed, priced on the curve."""
    day = int(snap.get("day", 0))
    last_day = int(snap.get("last_day", 29))
    census = tile_census(snap.get("own_tiles"))
    n_animals = census["n_animals"]
    left = days_left(day, last_day)
    feed_need = n_animals * left
    wheat_units = _units(snap.get("own_tiles"), day, last_day, "WHEAT", False,
                         snap.get("own_shed") or {})
    net = wheat_units - feed_need
    quote = (snap.get("prices") or {}).get("WHEAT") or MARKET_PARAMS["WHEAT"]["base"]
    if net >= 0:
        rev, sold = walked_revenue(
            "WHEAT", net, _inv(snap, "WHEAT"), snap.get("shops") or [],
            day, last_day, 0, floor_fraction)
        return {
            "wheat_units": wheat_units, "feed_need": feed_need, "net": net,
            "cash": float(rev), "sold": sold, "bought": 0, "buy_cost": 0.0,
        }
    short = -net
    return {
        "wheat_units": wheat_units, "feed_need": feed_need, "net": net,
        "cash": -short * quote, "sold": 0, "bought": short,
        "buy_cost": short * quote,
    }


def project_stay(snap, floor_fraction=0.30):
    """Expected and conservative STAY_H4 terminal cash (own farm only)."""
    money = float(snap.get("money") or 0)
    day = int(snap.get("day", 0))
    last_day = int(snap.get("last_day", 29))
    hire = remaining_hire_cost(day, last_day)
    wheat = net_wheat_cash(snap, floor_fraction)
    our_exp = our_second = opp_exp = 0.0
    our_units = {}
    opp_units = {}
    for product in OUTPUT_PRODUCTS:
        if product == "WHEAT":
            continue
        row = split_remaining_revenue(snap, product, True, True, floor_fraction)
        our_exp += row["our_rev_sym"]
        our_second += row["our_rev"]
        opp_exp += row["opp_rev"]
        our_units[product] = row["our_units"]
        opp_units[product] = row["opp_units"]
    stay_exp = money + our_exp + wheat["cash"] - hire
    stay_cons = money + our_second + wheat["cash"] - hire
    opp_money = snap.get("opp_money")
    opp_vis = None if opp_money is None else float(opp_money) + opp_exp
    gap_exp = None if opp_vis is None else stay_exp - opp_vis
    gap = None if opp_vis is None else stay_cons - opp_vis
    return {
        "cash": money,
        "hire_remaining": hire,
        "wheat": wheat,
        "our_remaining_rev_expected": our_exp,
        "our_remaining_rev_conservative": our_second,
        "opp_remaining_rev_expected": opp_exp,
        "stay_expected": stay_exp,
        "stay_conservative": stay_cons,
        "opp_cash": opp_money,
        "opp_visible_terminal": opp_vis,
        "gap_expected": gap_exp,
        "gap_conservative": gap,
        "our_remaining_units": our_units,
        "opp_remaining_units": opp_units,
        "days_left": days_left(day, last_day),
    }


def ceiling_metrics(snap):
    """Measurable saturation. No calendar day gate."""
    census = tile_census(snap.get("own_tiles"))
    n_quads = int(snap.get("n_quads") or 1)
    day = int(snap.get("day", 0))
    last_day = int(snap.get("last_day", 29))
    left = days_left(day, last_day)
    n_animals = census["n_animals"]
    spatial = census["fill"] >= 0.85 and census["empty"] <= 2
    livestock_full = n_animals >= 6 and census["empty"] == 0
    one_quad = n_quads <= 1
    # Time: a conversion cannot mature if remaining days < min first_yield
    # of any shop-backed product or animal. Not "day 25".
    min_animal_ok = any(
        day + ANIMALS[a]["first_yield_day"] <= last_day
        for a in CONVERT_ANIMALS)
    shop_crop_ok = any(
        day + CROPS[c]["first_yield_day"] <= last_day
        for c in CONVERT_CROPS if product_has_shop_channel(c))
    at_ceiling = spatial and livestock_full and one_quad
    return {
        "fill": round(census["fill"], 3),
        "owned": census["owned"],
        "empty": census["empty"],
        "n_animals": n_animals,
        "n_plants": census["n_plants"],
        "wheat": census["wheat"],
        "animals": census["animals"],
        "crops": census["crops"],
        "n_quads": n_quads,
        "spatial_ceiling": spatial and one_quad,
        "livestock_ceiling": livestock_full and one_quad,
        "at_ceiling": at_ceiling,
        "livestock_can_mature": min_animal_ok,
        "shop_crop_can_mature": shop_crop_ok,
        "any_conversion_can_mature": min_animal_ok or shop_crop_ok,
        "days_left": left,
        "wheat_cycles_left": remaining_wheat_cycles(day, last_day),
    }


def project_momentum(snap, floor_fraction=0.30):
    """Dawn report: ceiling + STAY terminal + opponent visible terminal + gap."""
    stay = project_stay(snap, floor_fraction)
    ceil = ceiling_metrics(snap)
    ev_per_day = 0.0
    if stay["days_left"]:
        ev_per_day = stay["our_remaining_rev_expected"] / stay["days_left"]
    opp_ev_per_day = 0.0
    if stay["days_left"]:
        opp_ev_per_day = stay["opp_remaining_rev_expected"] / stay["days_left"]
    stay["ev_per_day"] = ev_per_day
    stay["opp_ev_per_day"] = opp_ev_per_day
    stay["ceiling"] = ceil
    # Losing under STAY: conservative gap negative. Convert window: some
    # shop-backed or livestock package can still mature.
    stay["stay_projects_loss"] = (
        stay["gap_expected"] is not None and stay["gap_expected"] < 0)
    stay["convert_window_open"] = ceil["any_conversion_can_mature"]
    stay["unrecoverable"] = stay["stay_projects_loss"] and not ceil["any_conversion_can_mature"]
    return stay


def decide_stay_or_convert(snap, ranked=None, min_npv=0, min_expected=0,
                           floor_fraction=0.30, livestock_reserve=300,
                           land_reserve=500, min_deficit=1500):
    """STAY_H4 unless projected to lose AND a conservative package pays back.

    Smallest/lowest-cost viable package among those whose conservative NPV
    exceeds both `min_npv` and a quarter of the projected deficit (so a
    $400 package is not used to chase a $4k hole). Gaps smaller than
    `min_deficit` are treated as noise: STAY. If nothing qualifies, STAY
    — including when the deficit is unrecoverable.
    """
    report = project_momentum(snap, floor_fraction)
    if ranked is None:
        ranked = evaluate_opportunities(
            snap, min_npv=min_npv, min_expected=min_expected,
            floor_fraction=floor_fraction,
            livestock_reserve=livestock_reserve, land_reserve=land_reserve)
    stay = dict(ranked[0]) if ranked and ranked[0]["id"] == "STAY_H4" else dict(STAY)
    stay["decision_reason"] = "default"
    stay["momentum"] = {
        "gap_expected": report["gap_expected"],
        "gap_conservative": report["gap_conservative"],
        "stay_expected": report["stay_expected"],
        "stay_conservative": report["stay_conservative"],
        "opp_visible_terminal": report["opp_visible_terminal"],
        "at_ceiling": report["ceiling"]["at_ceiling"],
        "unrecoverable": report["unrecoverable"],
    }
    gap = report["gap_expected"]
    if gap is None or gap > -min_deficit:
        stay["decision_reason"] = "projected_to_win_or_tie"
        return stay
    if report["unrecoverable"]:
        stay["decision_reason"] = "unrecoverable_no_mature_conversion"
        return stay
    viable = [p for p in ranked if p["id"] != "STAY_H4" and not p.get("reject")]
    viable = [p for p in viable if p.get("conservative_npv", 0) > min_npv]
    if not viable:
        stay["decision_reason"] = "no_profitable_conversion"
        return stay
    need = max(min_npv, min(500.0, -gap * 0.25))
    useful = [p for p in viable if p["conservative_npv"] >= need]
    if not useful:
        stay["decision_reason"] = "conversion_too_small_vs_gap"
        return stay
    useful.sort(key=lambda p: (p["cost"], -p["conservative_npv"], p["payback_risk"]))
    pick = dict(useful[0])
    pick["decision_reason"] = "convert_closes_gap"
    pick["momentum"] = stay["momentum"]
    return pick
