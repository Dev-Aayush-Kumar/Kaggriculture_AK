"""Competition entry point.

Kaggle loads the last callable in this file and calls it once per turn. The
package lives in `src/kagg` in the repository and next to `main.py` in a
submission bundle, so both layouts are put on the path.

Runtime is stdlib-only and every action passes through the validator in
`kagg.actions`; a failure inside the planner costs one turn, never the episode.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (_HERE, os.path.join(_HERE, "src")):
    if os.path.isdir(os.path.join(_candidate, "kagg")) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from kagg.agent import Executor  # noqa: E402
from kagg.config import Config  # noqa: E402

# Official submission after Phase 18 (E70). H4 = P1-S plus wool harvest
# defer and last-day rescue feed. P1-S stays the named historical control
# in research/baselines.py. This file cannot import that module.
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
)

_executor = Executor(CONFIG)


def agent(observation, configuration=None):
    return _executor(observation, configuration)
