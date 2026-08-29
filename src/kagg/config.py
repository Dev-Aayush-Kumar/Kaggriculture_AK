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
    # Off by default so P1-S/H4 stay wheat-only. When set to a CROPS key
    # (typically "CARROT" or "TOMATO"), non-NW crop tiles are planted with
    # that crop instead of wheat. Livestock slots are pinned to tiles that
    # already hold animals so a later BUY_LAND does not orphan pastures.
    extra_crop = ""
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
    # Off by default so P1-S/H1/H3 stay unchanged. When on, a unit standing
    # on an animal that will escape at dusk (already one day unfed, not fed
    # today) spends a small last-day budget to FEED it, but only when the
    # remaining production exceeds the wheat base.
    endgame_rescue_feed = False
    # Off (<0) keeps the original plant-any-hour rule. When 0-23, PLANT is
    # refused after this hour so a same-day WATER can still land. The engine
    # starts consecutive_unwatered at 1 on the planting day; two unwatered
    # days kill the plant (harness "drought").
    plant_latest_hour = -1

    # Off (0) keeps the original feed PICKUP: min(shed wheat, n_animals).
    # When >0, a unit drawing wheat for FEED takes at most this many, so a
    # second unit does not empty the shed and trigger a market restock of
    # wheat that is still being carried.
    feed_pickup_cap = 0
    # Off by default so P1-S/H4 stay unchanged. When on, wheat already in
    # unit inventories counts toward the feed buffer, so the market does not
    # restock wheat that has only left the shed.
    feed_count_carried = False

    # --- H5 experimental gates (all default-off so H4 is unchanged) ---
    # Pin livestock to tiles they already occupy when land unlocks. extra_crop
    # already pins; this flag pins without changing the crop mix.
    pin_livestock = False
    # Require purse >= this amount before BUY_LAND. 0 = no extra cash gate.
    land_min_money = 0
    # Refuse BUY_LAND before this day. Negative = no extra day gate.
    land_min_day = -1
    # Do not target or buy animals before this day (melon-opener conversion).
    livestock_start_day = 0
    # Add this many sheep to the target once at least one extra quadrant is owned.
    sheep_after_land = 0
    # Add this many sheep to the target while YARN_STORE is in unlocked_shops.
    sheep_yarn_bonus = 0

    # --- late-game conversion (all default-off so H4 is unchanged) ---
    # When liquidating, do not BUY_PRODUCT wheat. Rescue-feed still uses
    # wheat already in hand. Off keeps the original sell-then-rebuy loop.
    liquidate_stop_feed_buy = False
    # When liquidating, skip the dawn HIRE batch (frees market slots).
    liquidate_stop_hire = False
    # When >= 0, harvest_defer is skipped once remaining days are at or
    # below this value, so wool can enter the shed during liquidation.
    # -1 keeps the original defer (H4).
    harvest_defer_force_days = -1
    # When on, stop buying wheat once remaining livestock quote-value is
    # below the remaining feed bill. Not a calendar gate.
    feed_roi_gate = False
    # When on, BUY_LAND + extra sheep only if quote-time NPV of n extra
    # sheep minus the next land price exceeds roi_expand_min_npv, and the
    # purse still covers land + sheep cost + livestock_reserve. Not a
    # calendar day==X gate. Off keeps H4 (no land, 3 sheep).
    roi_expand_enabled = False
    roi_expand_sheep = 3
    roi_expand_min_npv = 0

    # --- adaptive opportunity layer (default-off; H4 is unchanged) ---
    # When on, dawn of each day ranks packages against STAY_H4 and commits
    # only if conservative NPV clears opportunity_min_npv. Off never calls
    # the evaluator from the executor.
    opportunity_enabled = False
    opportunity_min_npv = 0
    opportunity_min_expected = 0
    opportunity_floor_fraction = 0.30

    # --- stay-vs-convert (default-off; H4 is unchanged) ---
    # When on, dawn ranks packages but commits a conversion only if STAY_H4
    # is projected to lose on visible remaining output AND a conservative
    # package still pays back. Off never calls the decider from the executor.
    # Not a calendar gate. Does not identify named opponents.
    ceiling_convert_enabled = False
    ceiling_convert_min_npv = 0
    ceiling_convert_min_expected = 0
    # Must be behind by more than this many dollars on the symmetric
    # cash+remaining-EV gap before a conversion is considered. Twin noise
    # is a few hundred to ~$1.5k; structural H5A holes are larger.
    ceiling_convert_min_deficit = 1500

    # --- elite mix (default-off; H4 is unchanged) ---
    # When on, empty crop tiles are allocated by kagg.econ.engine.choose_tile_use
    # (crop_only): melon opener while justified, then strawberry fill, wheat
    # as feed/backfill. Does not change labor, livestock targets, land, or
    # fertilizer. Not a calendar rule and not a copied action sequence.
    elite_mix_enabled = False
    # Melon occupancy policy for elite mix (None = E77 conservative absorption).
    # An int is a state occupancy cap (E78 M18 uses 18). Not a calendar batch.
    melon_policy = None
    # After the melon opener is saturated: "pa" = strawberry/wheat fill (E78);
    # "wheat_feed" = wheat only when feed binds (E78 MALL ablation).
    melon_fallback = "pa"

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
