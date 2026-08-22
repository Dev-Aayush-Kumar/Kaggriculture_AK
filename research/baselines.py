"""Explicit Phase-5 research configurations.

P1 is the immutable incumbent. These dicts are Config overrides only; they
do not change executor behaviour by themselves.
"""

CORE = dict(routing="zone_nearest", geese=0, cows=3, sheep=3, crops=("WHEAT",),
            hands_per_day=6, livestock_cap_enabled=True)

# B2 / P0: Phase-3B incumbent, flags off.
P0 = dict(CORE, move_ev_enabled=False, sell_defer_enabled=False)

# Phase-4 incumbent. Must stay byte-equivalent to the E14 P1 seat.
P1 = dict(CORE, move_ev_enabled=True, sell_defer_enabled=False)

# Phase-4 sell-timing variant. Not stacked onto P1 unless E20 says so.
P2 = dict(CORE, move_ev_enabled=False, sell_defer_enabled=True)
