"""Explicit research configurations.

These dicts are Config overrides only; they do not change executor behaviour
by themselves. P1 is the Phase-5 fallback. QD is the Phase-5 incumbent.
P1_S is the Phase-6 control: sell-defer on P1 with sale quantity off.
"""

CORE = dict(routing="zone_nearest", geese=0, cows=3, sheep=3, crops=("WHEAT",),
            hands_per_day=6, livestock_cap_enabled=True)

# B2 / P0: Phase-3B incumbent, flags off.
P0 = dict(CORE, move_ev_enabled=False, sell_defer_enabled=False,
          sale_qty_enabled=False)

# Phase-4 / Phase-5 fallback. sale_qty stays off.
P1 = dict(CORE, move_ev_enabled=True, sell_defer_enabled=False,
          sale_qty_enabled=False)

# Phase-4 sell-timing variant on B2, not stacked onto P1.
P2 = dict(CORE, move_ev_enabled=False, sell_defer_enabled=True,
          sale_qty_enabled=False)

# Phase-6 control: P1 plus sell-defer only.
P1_S = dict(P1, sell_defer_enabled=True, sale_qty_enabled=False)

# Phase-5 incumbent: P1-S plus the 0.15 sale-qty cap.
QD = dict(P1_S, sale_qty_enabled=True, sale_qty_floor=0.15)
