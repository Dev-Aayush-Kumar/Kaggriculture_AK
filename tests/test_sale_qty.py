"""Sale lots stay uncapped unless the quantity-floor flag is on."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.agent import capped_sale_qty  # noqa: E402
from kagg.config import Config  # noqa: E402
from kagg.econ.market import units_until_price  # noqa: E402
from kagg.econ.tables import MARKET_I0  # noqa: E402


def _call(**overrides):
    args = dict(qty=20, item="WOOL", inventory=MARKET_I0, sale_qty_floor=0.30,
                sale_qty_enabled=False, day=20, last_day=29, shed_used=10,
                shed_capacity=100, sale_qty_force_days=0, sale_qty_shed_frac=0.80)
    args.update(overrides)
    return capped_sale_qty(**args)


def test_default_config_leaves_sale_qty_off():
    assert Config().sale_qty_enabled is False
    assert Config(move_ev_enabled=True, livestock_cap_enabled=True).sale_qty_enabled is False
    assert Config().sale_qty_floor == 0.30


def test_flag_off_sells_the_whole_lot():
    assert _call(qty=40, sale_qty_enabled=False) == 40


def test_flag_on_stops_at_the_existing_price_curve_room():
    room = units_until_price("WOOL", MARKET_I0, 0.30)
    assert room > 0
    assert _call(qty=room + 25, sale_qty_enabled=True) == room
    assert _call(qty=3, sale_qty_enabled=True) == 3


def test_flag_on_dumps_the_lot_on_a_hard_loss_turn():
    assert _call(qty=40, day=29, last_day=29, sale_qty_enabled=True) == 40
    assert _call(qty=40, shed_used=80, sale_qty_enabled=True) == 40


def test_missing_inventory_leaves_the_lot_uncapped():
    assert _call(qty=12, inventory=None, sale_qty_enabled=True) == 12


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
