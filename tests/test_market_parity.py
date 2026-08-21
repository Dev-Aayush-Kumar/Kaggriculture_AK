"""Assert our economics module is bit-for-bit identical to the installed engine.

Run directly (`python tests/test_market_parity.py`) or under pytest. Any failure
here invalidates every downstream planning decision, so this is the gate test.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kaggle_environments.envs.kaggriculture import kaggriculture as eng  # noqa: E402

from kagg.econ import market, tables  # noqa: E402


def test_tables_match_engine():
    assert tables.CROPS == eng.CROPS
    assert tables.ANIMALS == eng.ANIMALS
    assert tables.PRODUCTS == eng.PRODUCTS
    assert tables.MARKET_PARAMS == eng.MARKET_PARAMS
    assert tables.SHOPS == eng.SHOPS
    assert tables.MARKET_I0 == eng.MARKET_I0
    assert tables.PRICE_FLOOR == eng.PRICE_FLOOR
    assert tables.HINGE_GAIN == eng.HINGE_GAIN
    assert tables.LAND_ORDER == eng.LAND_ORDER
    assert tables.LAND_PRICES == eng.LAND_PRICES
    assert tables.MAX_SHOP_INSTANCES == eng.MAX_SHOP_INSTANCES
    assert tables.TOWN_CENTER_PRODUCTS == eng.TOWN_CENTER_PRODUCTS
    assert tables.MOVES == eng.FARMER_MOVES


def test_shape_function_matches_engine():
    for func in ("linear", "sq", "sqrt", "log", "log10", "hinge"):
        for T in (1, 100, 105, 200, 332, 400, 450):
            for x in (0, 1, 7, 99, 100, 101, 250, 999, 5000, 20000):
                assert market._shape(func, x, T) == eng._shape(func, x, T), (func, T, x)


def test_price_matches_engine_exhaustively():
    """Sweep every product across a wide inventory band at unit resolution near I0."""
    checked = 0
    for item in tables.PRODUCTS:
        ranges = list(range(0, 9000, 250))
        ranges += list(range(9000, 11001))          # unit resolution around I0
        ranges += list(range(11000, 40001, 500))
        for inv in ranges:
            assert market.price(item, inv) == eng.market_price(item, inv), (item, inv)
            checked += 1
    print(f"  price() parity verified at {checked:,} (item, inventory) points")


def test_buy_price_round_trip_nets_zero():
    """Engine invariant: buy then sell against an unchanged market is free."""
    for item in tables.BUYABLE_PRODUCTS:
        for inv in (500, 5000, 9999, 10000, 10001, 15000):
            assert market.buy_price(item, inv) == market.price(item, inv - 1)


def test_fib_and_hire_cost_match_engine():
    for n in range(0, 20):
        assert tables.fib(n) == eng._fib(n), n
        assert tables.hire_cost(n) == eng._hire_cost(n), n
    # Ten hands in one day is the widely-quoted cheap-labour figure.
    assert tables.cumulative_hire_cost(10) == 143


def test_geometry_matches_engine():
    for bs in (4, 6, 10, 12):
        assert tables.shed_access_tiles(bs) == eng._shed_access_tiles(bs)
        for y in range(bs):
            for x in range(bs):
                assert tables.quadrant_of(x, y, bs) == eng._quadrant_of(x, y, bs)


def test_sell_revenue_matches_engine_commit_loop():
    """Replicate the engine's per-unit SELL loop, including the $1-floor rule that
    floored sales do not add supply."""
    for item in tables.PRODUCTS:
        for start in (9500, 10000, 10050):
            for qty in (1, 5, 37, 200):
                inv = start
                rev = 0
                for _ in range(qty):
                    p = eng.market_price(item, inv)
                    rev += p
                    if p > 1:
                        inv += 1
                ours_rev, ours_inv = market.sell_revenue(item, qty, start)
                assert (ours_rev, ours_inv) == (rev, inv), (item, start, qty)


def test_town_drain_matches_engine_semantics():
    """One day = 6 shop ticks + 1 town-centre tick at default intervals."""
    for shops in ([], ["BAKERY"], ["YARN_STORE"], ["YARN_STORE", "YARN_STORE"],
                  ["PET_CAFE", "FARMERS_MARKET", "BAKERY"]):
        for item in tables.PRODUCTS:
            expected = 0
            for step in range(24):
                if step % 4 == 0:
                    for name in shops:
                        products = eng.SHOPS[name]
                        if item in products:
                            expected += 2 if len(products) == 1 else 1
                if step % 24 == 0 and item in eng.TOWN_CENTER_PRODUCTS:
                    expected += 1
            got = market.town_drain_per_day(shops, item)
            assert abs(got - expected) < 1e-9, (shops, item, got, expected)


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
