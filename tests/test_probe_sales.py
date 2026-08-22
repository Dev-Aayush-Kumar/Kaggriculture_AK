"""Quote-time sale metrics used by the harness probe.

These numbers are the single-seller walk of the Phase-1 price curve. They are
not the engine's post-lockstep fill, and the test pins the helper, not a
strategy claim.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.econ.market import MARKET_I0, PRICE_FLOOR, price, sell_revenue  # noqa: E402
from kagg.econ.tables import MARKET_PARAMS  # noqa: E402

import harness as H  # noqa: E402


def test_quote_sale_matches_sell_revenue_and_counts_the_floor():
    qty = 5
    rev, floor = H.quote_sale("MILK", qty, MARKET_I0)
    expected, _ = sell_revenue("MILK", qty, MARKET_I0)
    assert rev == expected
    assert floor == 0
    assert price("MILK", MARKET_I0) == MARKET_PARAMS["MILK"]["base"]


def test_quote_sale_counts_units_already_on_the_one_dollar_floor():
    inv = MARKET_I0
    while price("MILK", inv) > PRICE_FLOOR:
        inv += 1
        assert inv - MARKET_I0 < 500
    rev, floor = H.quote_sale("MILK", 7, inv)
    assert floor == 7
    assert rev == 7 * PRICE_FLOOR


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
