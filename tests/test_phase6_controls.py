"""P1, P1-S, and QD differ only by the Phase-6 sale flags."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.config import Config  # noqa: E402


def _cfg(params):
    return Config(**params)


def _fields(cfg):
    return {k: getattr(cfg, k) for k in vars(Config)
            if not k.startswith("_") and not callable(getattr(Config, k))}


def test_p1_keeps_sale_qty_off_and_matches_the_phase4_core():
    p1 = _cfg(B.P1)
    assert p1.move_ev_enabled is True
    assert p1.sell_defer_enabled is False
    assert p1.sale_qty_enabled is False
    assert p1.cows == 3 and p1.sheep == 3
    assert p1.livestock_cap_enabled is True
    assert p1.routing == "zone_nearest"


def test_p1s_differs_from_p1_only_by_sell_defer():
    p1, p1s = _fields(_cfg(B.P1)), _fields(_cfg(B.P1_S))
    assert p1s["sell_defer_enabled"] is True
    assert p1s["sale_qty_enabled"] is False
    assert p1s["sell_defer_force_days"] == 0
    assert p1s["sell_defer_shed_frac"] == 0.80
    changed = {k for k in p1 if p1[k] != p1s[k]}
    assert changed == {"sell_defer_enabled"}


def test_qd_differs_from_p1s_only_by_sale_qty():
    p1s, qd = _fields(_cfg(B.P1_S)), _fields(_cfg(B.QD))
    assert qd["sell_defer_enabled"] is True
    assert qd["sale_qty_enabled"] is True
    assert qd["sale_qty_floor"] == 0.15
    changed = {k for k in p1s if p1s[k] != qd[k]}
    assert changed == {"sale_qty_enabled", "sale_qty_floor"}


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
