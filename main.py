"""Competition entry point.

Kaggle exec()s this file (so __file__ is undefined) and calls the last
callable once per turn. The submitted archive places the `kagg` package next
to this file; kaggle-environments appends that directory to sys.path for the
duration of the exec, so the import below needs no path hacks.

Runtime is stdlib-only and every action passes through the validator in
`kagg.actions`; a failure inside the planner costs one turn, never the episode.
"""

from kagg.agent import Executor
from kagg.config import Config

# Official submission: M18 (E78). One-quadrant melon occupancy cap 18,
# strawberry/wheat PA fill, frozen 6 hands, no land. H4 remains the named
# historical control in research/baselines.py. This file cannot import that
# module. Defaults already keep buy_land=0, fertilize_crops=False,
# melon_fallback="pa".
CONFIG = Config(
    routing="zone_nearest",
    geese=0,
    cows=3,
    sheep=3,
    crops=("WHEAT",),
    hands_per_day=6,
    livestock_cap_enabled=True,
    move_ev_enabled=True,
    sell_defer_enabled=True,
    sale_qty_enabled=False,
    sell_defer_force_days=0,
    sell_defer_shed_frac=0.80,
    harvest_defer_enabled=True,
    harvest_defer_wool_only=True,
    endgame_rescue_feed=True,
    elite_mix_enabled=True,
    melon_policy=18,
)

_executor = Executor(CONFIG)


def agent(observation, configuration=None):
    return _executor(observation, configuration)
