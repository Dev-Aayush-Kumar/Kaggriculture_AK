"""Lock in the mechanics that experiments/006_e7_timing.py established.

Each of these encodes a rule the strategy now depends on. They call the engine's
own refresh routines directly where possible, so they are fast and still
authoritative, and drive real episodes where the question is about episode
structure or the market.
"""

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make
    from kaggle_environments.envs.kaggriculture import kaggriculture as eng

TPD = 24
IDLE = {"farmer": ["PASS"], "hands": [], "market": []}


def _farm_with(tile):
    farm = eng._new_farm(10, 0)
    farm["tiles"][0][0] = tile
    farm["farmer"] = [0, 0]     # stand the farmer on the tile under test
    return farm


def _kind(farm):
    tile = farm["tiles"][0][0]
    return tile.get("kind") if isinstance(tile, dict) else tile


# ------------------------------------------------------------------- watering

def test_a_new_plant_dies_unless_watered_on_its_planting_day():
    """The planting day already counts as one dry day, so day one is not free."""
    for watered in (True, False):
        farm = _farm_with(eng._new_plant("WHEAT", 0, TPD))
        assert farm["tiles"][0][0]["consecutive_unwatered"] == 1
        farm["tiles"][0][0]["watered_today"] = watered
        eng._daily_refresh_plants(farm, 0, TPD)
        assert _kind(farm) == ("PLANT" if watered else "WEED"), watered


def test_watering_every_other_day_keeps_a_crop_alive():
    outcomes = {}
    for interval in (1, 2, 3):
        farm = _farm_with(eng._new_plant("MELON", 0, TPD))
        died = None
        for day in range(9):
            if _kind(farm) != "PLANT":
                died = day
                break
            farm["tiles"][0][0]["watered_today"] = (day % interval == 0)
            eng._daily_refresh_plants(farm, day, TPD)
        outcomes[interval] = died
    assert outcomes[1] is None and outcomes[2] is None, outcomes
    assert outcomes[3] is not None, "three dry days in a row must kill a crop"


def test_watering_in_the_bonus_window_adds_yield_immediately():
    """WATER credits yield inside _apply_unit_action, not at end of day, which is
    why it still pays on the final turn of the season."""
    farm = _farm_with(eng._new_plant("WHEAT", 0, TPD))
    private = eng._new_private()
    window_start = (eng.CROPS["WHEAT"]["max_yield_day"] + 1) // 2
    before = farm["tiles"][0][0]["yield_units"]
    eng._apply_unit_action(farm, private, 0, ["WATER"], 10, window_start, TPD, 100)
    assert farm["tiles"][0][0]["yield_units"] == before + 1

    farm["tiles"][0][0]["watered_today"] = False
    farm["tiles"][0][0]["fertilized_until_day"] = window_start
    before = farm["tiles"][0][0]["yield_units"]
    eng._apply_unit_action(farm, private, 0, ["WATER"], 10, window_start, TPD, 100)
    assert farm["tiles"][0][0]["yield_units"] == before + 2, "fertilizer doubles it"


# ---------------------------------------------------------------------- decay

def test_decay_begins_one_day_after_max_yield_and_costs_a_unit_every_two_steps():
    farm = _farm_with(eng._new_plant("WHEAT", 0, TPD))
    farm["tiles"][0][0]["yield_units"] = 3
    mls = farm["tiles"][0][0]["max_lifespan_step"]
    assert mls == (0 + eng.CROPS["WHEAT"]["max_yield_day"] + 1) * TPD

    losses = []
    for step in range(mls - 6, mls + 14):
        before = farm["tiles"][0][0]
        prior = before["yield_units"] if _kind(farm) == "PLANT" else 0
        eng._decay_plants(farm, step)
        now = farm["tiles"][0][0]["yield_units"] if _kind(farm) == "PLANT" else 0
        if now < prior:
            losses.append(step)
    assert losses == [mls, mls + 2, mls + 4], losses
    assert _kind(farm) == "WEED", "the tile becomes a weed once the yield hits zero"


# -------------------------------------------------------------------- animals

def test_care_bonus_is_paid_on_the_production_after_next():
    """CARE banks a unit at end of day D and it is cashed at end of day D+1."""
    farm = _farm_with(eng._new_animal("GOOSE", 0))
    gains = []
    for day in range(8):
        tile = farm["tiles"][0][0]
        tile["yield_units"] = 0                 # stand in for a daily harvest
        tile["fed_today"] = True
        tile["cared_today"] = (day == 4)        # care on exactly one day
        eng._daily_refresh_animals(farm, day)
        gains.append(farm["tiles"][0][0]["yield_units"])
    # GOOSE first_yield_day 4: production starts at the end of day 3, and the
    # single day of care shows up two refreshes later.
    assert gains == [0, 0, 0, 1, 1, 2, 1, 1], gains


def test_animals_produce_on_days_they_were_not_fed():
    """Feeding guards against escape and unlocks the CARE bonus; it is not a
    precondition for the base yield."""
    farm = _farm_with(eng._new_animal("GOOSE", 0))
    for day in range(4):
        tile = farm["tiles"][0][0]
        tile["yield_units"] = 0
        tile["fed_today"] = (day % 2 == 0)      # fed on even days only
        eng._daily_refresh_animals(farm, day)
    tile = farm["tiles"][0][0]
    assert "animal" in tile, "alternate-day feeding must not lose the animal"
    assert tile["yield_units"] == 1, "produced at end of day 3 while unfed"


def test_two_consecutive_unfed_days_lose_the_animal():
    farm = _farm_with(eng._new_animal("GOOSE", 0))
    eng._daily_refresh_animals(farm, 0)
    assert "animal" in farm["tiles"][0][0]
    eng._daily_refresh_animals(farm, 1)
    assert farm["tiles"][0][0] == {"kind": "COOP"}, "structure stays, animal escapes"


# ----------------------------------------------------------------------- shed

def test_end_of_day_drop_discards_everything_above_capacity():
    private = eng._new_private()
    private["shed"]["WHEAT"] = 90
    private["inventories"] = [{"EGG": 20}, {"MILK": 5}]
    eng._drop_inventories_to_shed(private, 100)
    assert sum(private["shed"].values()) == 100
    assert all(not inv for inv in private["inventories"]), "hands are always emptied"


# -------------------------------------------------------------- episode shape

def test_last_actionable_turn_is_episode_steps_minus_two():
    steps = 3 * TPD
    env = make("kaggriculture", configuration={"episodeSteps": steps, "seed": 1})
    env.reset(num_agents=2)
    seen = []
    while not env.done:
        obs = env.state[0].observation
        seen.append((obs["step"], obs["day"], obs["hour"]))
        env.step([IDLE, IDLE])
    assert seen[-1][0] == steps - 2, seen[-1]
    assert (seen[-1][1], seen[-1][2]) == ((steps - 2) // TPD, (steps - 2) % TPD)


def test_drop_and_sell_on_the_final_turn_banks_carried_stock():
    """Unit actions resolve before the market, so the last turn can still bank
    produce -- but only if it is dropped rather than left in hand."""
    steps = 3 * TPD
    final_step = steps - 2
    results = {}

    for drop in (True, False):
        env = make("kaggriculture", configuration={"episodeSteps": steps, "seed": 1})
        env.reset(num_agents=2)
        while not env.done:
            obs = env.state[0].observation
            shed = obs["private"]["shed"]
            inv = obs["private"]["inventories"][0]
            action = dict(IDLE)
            if obs["step"] == 0:
                action = {"farmer": ["PASS"], "hands": [],
                          "market": [["BUY_PRODUCT", "WHEAT", 10]]}
            elif obs["step"] == final_step - 1 and shed.get("WHEAT", 0) >= 10:
                action = {"farmer": ["PICKUP", "WHEAT", 10], "hands": [], "market": []}
            elif obs["step"] == final_step:
                action = {"farmer": ["DROP"] if drop else ["PASS"], "hands": [],
                          "market": [["SELL", "WHEAT", 10]]}
            env.step([action, IDLE])
        results[drop] = env.steps[-1][0].observation["farms"][0]["money"]

    assert results[True] > results[False], results
    assert not results[False] > results[True]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
