"""Explicit research configurations.

These dicts are Config overrides only; they do not change executor behaviour
by themselves. P1 is the Phase-5 fallback. QD is the Phase-5 incumbent.
P1_S is the Phase-6 historical control. H4 is the Phase-18 official champion.
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

# Phase-6 historical control: P1 plus sell-defer only. Last-day force dump.
# Kept for paired experiments. No longer the official submission after E70.
P1_S = dict(P1, sell_defer_enabled=True, sale_qty_enabled=False,
            sell_defer_force_days=0, sell_defer_shed_frac=0.80)

# Official research champion and Kaggle submission after Phase 18 (E70).
# Differs from P1_S only by the three stacked harvest/rescue flags.
H4 = dict(P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)

# Phase-5 incumbent: P1-S plus the 0.15 sale-qty cap.
QD = dict(P1_S, sale_qty_enabled=True, sale_qty_floor=0.15)
