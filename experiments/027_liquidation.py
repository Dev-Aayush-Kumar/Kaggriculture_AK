"""E27 - document the existing endgame liquidation surface.

No engine episodes. P1-S already waits until the last day before forcing a
poor-quote dump. That knob is sell_defer_force_days.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
from kagg.agent import sale_justified  # noqa: E402
from kagg.config import Config  # noqa: E402


def main():
    cfg = Config(**B.P1_S)
    print("P1-S liquidation surface")
    print(f"  sell_defer_enabled={cfg.sell_defer_enabled}")
    print(f"  sell_defer_force_days={cfg.sell_defer_force_days}  "
          "(0 = last day only)")
    print(f"  sell_defer_shed_frac={cfg.sell_defer_shed_frac}")
    print(f"  liquidate_before_end={cfg.liquidate_before_end}  "
          "(wheat/acquisitions only when defer is on)")
    print(f"  sale_qty_enabled={cfg.sale_qty_enabled}")
    last = 29
    for force, label in ((0, "L0/P1-S"), (1, "L3 last two days"),
                         (-1, "L2 never time-force")):
        dump = [d for d in range(25, last + 1)
                if sale_justified(1, 200, d, last, 10, 100, 0.30, True,
                                  True, force, 0.80)]
        print(f"  {label}: poor-quote dump days {dump}")
    print("E27: existing surface is sell_defer_force_days; P1-S stays at 0.")


if __name__ == "__main__":
    main()
