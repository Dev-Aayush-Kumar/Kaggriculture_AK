"""Every tunable in one place.

Strategy families are expressed as `Config` instances, so a portfolio experiment
is a list of configs rather than a list of agent classes.
"""


class Config:
    # --- labour
    # Hiring is the cheapest thing on the board: six hands cost $20 for a whole
    # day and multiply the action budget sevenfold, so the reserve is token.
    hands_per_day = 6          # HIRE requests issued at the start of each day
    hire_hour = 0
    hire_reserve = 30

    # --- routing policy under test: "nearest" | "zone" | "zone_nearest"
    routing = "nearest"

    # --- livestock (placed on the tiles closest to the shed)
    geese = 4
    cows = 0
    sheep = 0
    care = True
    collect_fertilizer = True

    # --- crops (rotated over the remaining tiles)
    crops = ("WHEAT",)
    fertilize_crops = False
    max_crop_tiles = 25
    tiles_per_unit = 3.0       # crop tiles opened per planned crew member

    # --- market
    feed_buffer = 2            # wheat kept in the shed per animal
    sell_floor_fraction = 0.30  # hold produce quoted below this share of base...
    liquidate_before_end = 2   # ...until this many days from the end, then dump
    # Off by default so P0/B2 is unchanged. When on, a quote below
    # sell_floor_fraction is not dumped during the liquidation window unless
    # remaining days are at or below sell_defer_force_days or the shed is
    # approaching capacity (the hard-loss conditions).
    sell_defer_enabled = False
    # Remaining days at or below this value force a poor-quote dump.
    # 0 = last day only (P1-S). 1 = last two days. Negative = never time-force.
    sell_defer_force_days = 0
    sell_defer_shed_frac = 0.80
    # Land unlocks in the engine's fixed order NE, SW, SE at $1k/$2k/$4k, so the
    # only decision is how many to buy.
    buy_land = 0
    land_reserve = 500         # keep this much liquid after buying land
    livestock_reserve = 300    # cash kept back when stocking animals
    seed_reserve = 150         # cash kept back when buying seed
    seed_batch = 8             # seeds bought per crop per turn at most
    # Off by default so B0 is unchanged. When on, extra animals of a type are
    # refused once own projected output would exceed remaining profitable
    # absorption (town demand + units until the price floor).
    livestock_cap_enabled = False
    livestock_absorb_slack = 1.0
    livestock_cap_floor = 0.30
    # Off by default so P1 is unchanged. When on, a sale lot is truncated to
    # units_until_price(..., sale_qty_floor) unless remaining days are at or
    # below sale_qty_force_days or the shed is approaching capacity.
    sale_qty_enabled = False
    sale_qty_floor = 0.30
    sale_qty_force_days = 0
    sale_qty_shed_frac = 0.80

    # Off by default so P1-S is unchanged. When on, animal harvest is skipped
    # while the product quote is below harvest_defer_floor_fraction, unless
    # the tile is at max_held (the hard-loss rescue).
    harvest_defer_enabled = False
    harvest_defer_floor_fraction = 0.30
    # Off by default so H1 is unchanged. When on with harvest_defer, a full
    # tile is also held at a poor quote until the existing last-day force.
    harvest_defer_hold_full = False
    # Off by default so H1 is unchanged. When on with harvest_defer, only
    # wool is held; milk stays on the original always-lift rule.
    harvest_defer_wool_only = False

    # --- safety
    drop_threshold = 4         # carry this many items before making a shed trip
    # Off by default so P0/B2 is unchanged. When on, an idle shed walk is taken
    # only if the carried quote-value covers min_trip_value_per_step per tile,
    # except in the last hours of the day when the free end-of-day drop is near
    # and a late walk is the hard-loss alternative.
    move_ev_enabled = False
    min_trip_value_per_step = 10
    turn_budget_ms = 250       # hard stop; the engine allows 1000 ms

    def __init__(self, **overrides):
        for key, value in overrides.items():
            if not hasattr(Config, key):
                raise AttributeError(f"unknown config field: {key}")
            setattr(self, key, value)

    def replace(self, **overrides):
        merged = {k: getattr(self, k) for k in vars(Config) if not k.startswith("_")
                  and not callable(getattr(Config, k))}
        merged.update(overrides)
        return Config(**merged)

    def __repr__(self):
        fields = {k: getattr(self, k) for k in vars(self)}
        return "Config(" + ", ".join(f"{k}={v!r}" for k, v in sorted(fields.items())) + ")"
