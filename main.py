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

# Provisional: the portfolio is still being screened, so this is the reference
# configuration rather than a committed strategy.
CONFIG = Config(
    routing="zone_nearest",
    geese=4,
    crops=("WHEAT",),
    hands_per_day=6,
)

_executor = Executor(CONFIG)


def agent(observation, configuration=None):
    return _executor(observation, configuration)
