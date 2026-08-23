"""E22 - lock the Phase-6 control configurations.

No engine episodes. Prints the explicit P1 / P1-S / QD Config diffs and
exits non-zero if they are not isolated to the sale flags.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.config import Config  # noqa: E402


def fields(params):
    cfg = Config(**params)
    return {k: getattr(cfg, k) for k in vars(Config)
            if not k.startswith("_") and not callable(getattr(Config, k))}


def diff(a, b):
    fa, fb = fields(a), fields(b)
    return {k: (fa[k], fb[k]) for k in fa if fa[k] != fb[k]}


def main():
    print("P1", B.P1)
    print("P1_S", B.P1_S)
    print("QD", B.QD)
    print("P1 vs P1_S", diff(B.P1, B.P1_S))
    print("P1_S vs QD", diff(B.P1_S, B.QD))
    print("P1 vs QD", diff(B.P1, B.QD))
    assert diff(B.P1, B.P1_S) == {"sell_defer_enabled": (False, True)}
    assert diff(B.P1_S, B.QD) == {
        "sale_qty_enabled": (False, True),
        "sale_qty_floor": (0.30, 0.15),
    }
    assert fields(B.P1)["sale_qty_enabled"] is False
    print("E22 PASSED: P1, P1-S, and QD are isolated Config controls.")


if __name__ == "__main__":
    main()
