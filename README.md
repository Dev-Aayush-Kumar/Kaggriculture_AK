# Kaggriculture_AK

Agent for the Kaggriculture competition. The real `kaggle-environments` engine is
the only source of truth here: every mechanic the strategy relies on is
confirmed by a probe and then pinned by a regression test.

## Layout

| Path | Role |
| --- | --- |
| `main.py` | Competition entry point |
| `src/kagg/` | Submitted agent. **Stdlib only.** |
| `src/kagg/econ/` | Engine tables and an exact reimplementation of the price curve |
| `src/kagg/actions.py` | Action vocabulary and legality checks, transcribed from the engine |
| `src/kagg/agent.py` | The executor: tasks, routing, market planning, validation |
| `src/kagg/config.py` | Every tunable, in one place |
| `research/harness.py` | Seeded episode runner, instrumentation, aggregation |
| `experiments/` | Numbered one-off experiments |
| `tests/` | Regression tests (no pytest needed; each file runs standalone) |
| `results/` | Raw JSON/CSV from experiment runs |

Research code and submission code are kept apart: nothing under `src/kagg`
imports from `research/` or `experiments/`.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

## Running things

```bash
.venv/Scripts/python tests/test_market_parity.py   # price curve == engine
.venv/Scripts/python tests/test_action_rules.py    # validator == engine
.venv/Scripts/python tests/test_mechanics.py       # confirmed game mechanics

.venv/Scripts/python experiments/003_harness_smoke.py
.venv/Scripts/python experiments/005_e3_routing.py
.venv/Scripts/python experiments/006_e7_timing.py
.venv/Scripts/python experiments/007_portfolio_screen.py
```

An episode costs about 13 s of framework overhead regardless of the agent, so
the harness spreads episodes across cores. Agent time itself is under 10 ms per
turn against a 1 s limit.

## Confirmed mechanics

Established experimentally in `experiments/006_e7_timing.py` and locked in
`tests/test_mechanics.py`:

- The last actionable turn is step `episodeSteps - 2`; no end-of-day refresh
  follows it, so stock left in a farmer's hands is lost. Unit actions resolve
  before the market, so `DROP` and `SELL` on that same final turn still bank it.
- A crop must be watered on the day it is planted; the planting day already
  counts as one dry day. After that, every other day is enough to survive.
- Watering inside the bonus window credits yield immediately, so it pays right
  up to the final turn. Fertilizer doubles that bonus.
- Decay starts at `(planted_day + max_yield_day + 1) * turnsPerDay` and removes
  one unit every two steps until the tile becomes a weed.
- `CARE` is banked at end of day and cashed at the *next* production, so it pays
  with a two-day lag and is worthless in the last two days.
- Animals produce on days they were not fed. Feeding guards against escape (two
  consecutive misses) and unlocks the `CARE` bonus.
- The end-of-day drop fills the shed to capacity and silently discards the rest.
