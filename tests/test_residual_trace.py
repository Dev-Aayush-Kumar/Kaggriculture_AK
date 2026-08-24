"""Pin the E35 residual-wool classifiers. They label traces; they do not change play."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import harness as H  # noqa: E402


def test_product_on_tiles_counts_held_and_full():
    farm = {"tiles": [
        [{"animal": "SHEEP", "yield_units": 6},
         {"animal": "SHEEP", "yield_units": 2},
         {"kind": "PLANT", "crop": "WHEAT", "yield_units": 4}],
        [{"animal": "COW", "yield_units": 6}, None],
    ]}
    held, full = H._product_on_tiles(farm, "WOOL")
    assert held == 8
    assert full == 6
    milk, milk_full = H._product_on_tiles(farm, "MILK")
    assert milk == 6
    assert milk_full == 6


def test_classify_floor_sale_keeps_the_e31_labels():
    assert H.classify_floor_sale(
        {"item": "WOOL", "day": 20, "quote": 1}) == "mid_already_floor"
    assert H.classify_floor_sale(
        {"item": "WOOL", "day": 20, "quote": 40}) == "mid_poor_forced"
    assert H.classify_floor_sale(
        {"item": "WOOL", "day": 20, "quote": 80}) == "mid_lot_walk"
    assert H.classify_floor_sale(
        {"item": "WOOL", "day": 29, "quote": 40}) == "last_day_poor_forced"


def test_harvest_is_rescue_only_for_full_poor_tiles():
    assert H.harvest_is_rescue(
        {"item": "WOOL", "full": True, "quote": 1}) is True
    assert H.harvest_is_rescue(
        {"item": "WOOL", "full": True, "quote": 80}) is False
    assert H.harvest_is_rescue(
        {"item": "WOOL", "full": False, "quote": 1}) is False


def test_pickup_return_feed_cost_is_one_with_wheat_else_round_trip():
    assert H.pickup_return_feed_cost(2, 1) == 1
    assert H.pickup_return_feed_cost(2, 0) == 6
    assert H.pickup_return_feed_cost(0, 0) == 2
    assert H.pickup_return_feed_cost(1, 0) == 4


def test_escape_seen_at_dawn_is_the_previous_day():
    assert H.escape_obs_to_loss_day(29, 0) == 28
    assert H.escape_obs_to_loss_day(28, 0) == 27
    assert H.escape_obs_to_loss_day(28, 12) == 28


def test_farm_day_snapshot_counts_animals_shed_and_tile_yield():
    farm = {"tiles": [
        [{"animal": "SHEEP", "yield_units": 6},
         {"animal": "COW", "yield_units": 2}],
    ]}
    private = {"shed": {"WOOL": 12, "WHEAT": 8, "MILK": 3}}
    snap = H.farm_day_snapshot(farm, private)
    assert snap["animals"] == 2
    assert snap["shed"]["used"] == 23
    assert snap["shed"]["WOOL"] == 12
    assert snap["tile"]["WOOL"] == 6
    assert snap["tile"]["WOOL_full"] == 6
    assert snap["tile"]["MILK"] == 2


def test_sell_defer_bypass_names_the_existing_force_paths():
    assert H.sell_defer_bypass(
        {"item": "WOOL", "day": 29, "quote": 1, "shed_used": 10}) == "force_days"
    assert H.sell_defer_bypass(
        {"item": "WOOL", "day": 20, "quote": 1, "shed_used": 80}) == "shed_frac"
    assert H.sell_defer_bypass(
        {"item": "WOOL", "day": 20, "quote": 80, "shed_used": 80}) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
