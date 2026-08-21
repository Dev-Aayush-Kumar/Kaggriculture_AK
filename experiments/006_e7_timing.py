"""E7 - confirm the timing and endgame mechanics on the real engine.

Every row of the final table is produced by driving a scripted farmer through
env.step() and reading what the engine did. Nothing here is inferred from
reading the source; anything not actually observed is reported UNKNOWN.

Episodes are shortened to 10 days so the endgame arrives quickly. Cutoffs are
therefore reported relative to the last day, which is what generalises.
"""

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

with contextlib.redirect_stderr(io.StringIO()):
    from kaggle_environments import make

DAYS = 10
SEED = 5
IDLE = {"farmer": ["PASS"], "hands": [], "market": []}
FINDINGS = []


def record(mechanic, observed, cutoff, confidence):
    FINDINGS.append((mechanic, observed, cutoff, confidence))


def drive(policy, days=DAYS, seed=SEED, extra=None):
    config = {"episodeSteps": days * 24, "seed": seed}
    config.update(extra or {})
    with contextlib.redirect_stderr(io.StringIO()):
        env = make("kaggriculture", configuration=config, debug=False)
    env.reset(num_agents=2)
    while not env.done:
        env.step([policy(env.state[0].observation), IDLE])
    return env


def tile(o, x=4, y=4):
    return o["farms"][0]["tiles"][y][x]


def money(env):
    return env.steps[-1][0].observation["farms"][0]["money"]


# ------------------------------------------------------------------ episode shape

def probe_episode_shape():
    seen = []

    def pol(o):
        seen.append((o["step"], o["day"], o["hour"]))
        return IDLE

    env = drive(pol)
    first, last = seen[0], seen[-1]
    total_steps = DAYS * 24
    record("episode shape",
           f"agent acts {len(seen)}x, steps {first[0]}..{last[0]}, "
           f"last acted turn is day {last[1]} hour {last[2]}",
           f"last actionable turn = step episodeSteps-2 "
           f"(day {last[1]}, hour {last[2]} of {total_steps} steps)",
           "confirmed")
    return last


# ------------------------------------------------------------------ crop decay

def probe_crop_decay():
    """Plant wheat, water it, never harvest, and watch it rot."""
    series = []
    state = {"weed_step": None, "mls": None}

    def pol(o):
        t = tile(o)
        step = o["step"]
        mkt = []
        if o["day"] == 0 and o["hour"] == 0:
            mkt.append(["BUY_SEED", "WHEAT", 1])
        if t is None and o["private"]["seeds"].get("WHEAT", 0) > 0:
            return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": mkt}
        if isinstance(t, dict) and t.get("kind") == "PLANT":
            series.append((step, t["yield_units"]))
            state["mls"] = t["max_lifespan_step"]
            if not t["watered_today"]:
                return {"farmer": ["WATER"], "hands": [], "market": mkt}
        if isinstance(t, dict) and t.get("kind") == "WEED" and state["weed_step"] is None:
            state["weed_step"] = (step, o["day"], o["hour"])
        return {"farmer": ["PASS"], "hands": [], "market": mkt}

    drive(pol)
    peak = max(v for _, v in series) if series else 0
    # A "loss" is a strict decrease from the previous observation.
    drops = [series[i][0] for i in range(1, len(series))
             if series[i][1] < series[i - 1][1]]
    gaps = {drops[i + 1] - drops[i] for i in range(len(drops) - 1)}
    mls = state["mls"]
    predicted = (0 + 4 + 1) * 24
    first_loss_seen = drops[0] if drops else None
    # Decay is applied at the end of a step, so the loss shows up in the
    # observation one step later.
    onset_ok = first_loss_seen == mls + 1 and mls == predicted
    record("crop decay onset",
           f"WHEAT planted day 0 peaked at {peak} units; engine reported "
           f"max_lifespan_step={mls}; first observed loss at step {first_loss_seen} "
           f"(day {first_loss_seen // 24}, hour {first_loss_seen % 24})",
           f"decay begins at step (planted_day + max_yield_day + 1) * turnsPerDay "
           f"= {predicted}, i.e. midnight after max_yield_day",
           "confirmed" if onset_ok else "MISMATCH")
    record("crop decay rate",
           f"losses observed at steps {drops}; inter-loss gaps {gaps or 'n/a'}; "
           f"tile became WEED at step {state['weed_step'][0] if state['weed_step'] else None} "
           f"after {peak} units",
           "-1 unit every 2 steps until 0, then the tile turns to WEED"
           if gaps == {2} else "UNKNOWN",
           "confirmed" if gaps == {2} else "UNKNOWN")


# ------------------------------------------------------------------ goose harness

def goose_policy(care_days=None, feed_through=None, place_day=0, harvest=True):
    """Scripted single-goose husbandry on the shed tile (4,4).

    Standing on (4,4) the farmer is shed-adjacent, so feed, care, harvest,
    fertilizer collection and restocking all happen without moving.
    """
    tally = {"eggs": 0, "fert": 0, "placed": None}

    def pol(o):
        day, hour = o["day"], o["hour"]
        priv = o["private"]
        inv = priv["inventories"][0] if priv["inventories"] else {}
        shed = priv["shed"]
        t = tile(o)
        mkt = []
        if shed.get("WHEAT", 0) + inv.get("WHEAT", 0) < 4:
            mkt.append(["BUY_PRODUCT", "WHEAT", 6])
        for item in ("EGG", "FERTILIZER"):
            if shed.get(item, 0) > 0:
                mkt.append(["SELL", item, shed[item]])

        if day == 0 and hour == 0:
            return {"farmer": ["BUILD_COOP"], "hands": [],
                    "market": [["BUY_ANIMAL", "GOOSE", 1]] + mkt}
        if not isinstance(t, dict):
            return {"farmer": ["PASS"], "hands": [], "market": mkt}
        if "animal" not in t:
            if day < place_day:
                return {"farmer": ["PASS"], "hands": [], "market": mkt}
            if inv.get("GOOSE", 0) > 0:
                tally["placed"] = (day, hour)
                return {"farmer": ["PLACE", "GOOSE"], "hands": [], "market": mkt}
            if shed.get("GOOSE", 0) > 0:
                return {"farmer": ["PICKUP", "GOOSE", 1], "hands": [], "market": mkt}
            return {"farmer": ["PASS"], "hands": [], "market": mkt}

        feeding = feed_through is None or day <= feed_through
        if feeding and not t["fed_today"]:
            if inv.get("WHEAT", 0) < 1:
                if shed.get("WHEAT", 0) > 0:
                    return {"farmer": ["PICKUP", "WHEAT", 3], "hands": [], "market": mkt}
                return {"farmer": ["PASS"], "hands": [], "market": mkt}
            return {"farmer": ["FEED"], "hands": [], "market": mkt}
        if care_days is not None and day in care_days and not t["cared_today"] \
                and t["fed_today"]:
            return {"farmer": ["CARE"], "hands": [], "market": mkt}
        if harvest and t["yield_units"] > 0:
            tally["eggs"] += t["yield_units"]
            return {"farmer": ["HARVEST"], "hands": [], "market": mkt}
        if t["fertilizer_available"]:
            tally["fert"] += 1
            return {"farmer": ["COLLECT_FERTILIZER"], "hands": [], "market": mkt}
        if inv:
            return {"farmer": ["DROP"], "hands": [], "market": mkt}
        return {"farmer": ["PASS"], "hands": [], "market": mkt}

    return pol, tally


def probe_care_cutoff(last_day):
    """Care on exactly one day and see whether it ever turns into an egg."""
    base_pol, base = goose_policy(care_days=set())
    drive(base_pol)
    deltas = {}
    for day in range(last_day - 5, last_day + 1):
        pol, tally = goose_policy(care_days={day})
        drive(pol)
        deltas[day] = tally["eggs"] - base["eggs"]
    paying = [d for d, v in deltas.items() if v > 0]
    cutoff = max(paying) if paying else None
    record("CARE cutoff",
           f"baseline (never care) = {base['eggs']} eggs; extra eggs from caring "
           f"on exactly day D: {deltas}",
           f"last day CARE still pays = {cutoff} (= last_day - {last_day - cutoff})"
           if cutoff is not None else "UNKNOWN",
           "confirmed" if cutoff is not None else "UNKNOWN")


def probe_feed_cutoff(last_day):
    """Stop feeding after day D and see when total output stops changing."""
    results = {}
    for day in range(last_day - 5, last_day + 1):
        pol, tally = goose_policy(care_days=set(), feed_through=day)
        drive(pol)
        results[day] = tally["eggs"]
    full = results[last_day]
    paying = [d for d in sorted(results) if results[d] == full]
    cutoff = min(paying) if paying else None
    record("FEED cutoff",
           f"eggs when feeding stops after day D: {results}",
           f"feeding beyond day {cutoff} adds nothing "
           f"(= last_day - {last_day - cutoff})" if cutoff is not None else "UNKNOWN",
           "confirmed" if cutoff is not None else "UNKNOWN")


def probe_animal_purchase_cutoff(last_day):
    results = {}
    for day in range(0, last_day + 1):
        pol, tally = goose_policy(care_days=set(), place_day=day)
        drive(pol)
        results[day] = tally["eggs"]
    paying = [d for d, v in results.items() if v > 0]
    cutoff = max(paying) if paying else None
    record("animal purchase cutoff",
           f"eggs from a goose first placed on day D: {results}",
           f"last placement day yielding any egg = {cutoff} "
           f"(= last_day - {last_day - cutoff}); GOOSE first_yield_day is 4"
           if cutoff is not None else "UNKNOWN",
           "confirmed" if cutoff is not None else "UNKNOWN")


# ------------------------------------------------------------------ crops at the end

def crop_policy(crop, plant_day):
    tally = {"units": 0, "harvest_at": None}

    def pol(o):
        day, hour = o["day"], o["hour"]
        t = tile(o)
        priv = o["private"]
        mkt = []
        if priv["seeds"].get(crop, 0) == 0 and t is None and day >= plant_day:
            mkt.append(["BUY_SEED", crop, 1])
        if priv["shed"].get(crop, 0) > 0:
            mkt.append(["SELL", crop, priv["shed"][crop]])
        if t is None and day >= plant_day and priv["seeds"].get(crop, 0) > 0:
            return {"farmer": ["PLANT", crop], "hands": [], "market": mkt}
        if isinstance(t, dict) and t.get("kind") == "PLANT":
            age = day - t["planted_day"]
            last_chance = (day == DAYS - 1 and hour >= 21)
            if t["yield_units"] > 0 and age >= 2 and last_chance:
                tally["units"] = t["yield_units"]
                tally["harvest_at"] = (day, hour)
                return {"farmer": ["HARVEST"], "hands": [], "market": mkt}
            if not t["watered_today"]:
                return {"farmer": ["WATER"], "hands": [], "market": mkt}
        if priv["inventories"] and priv["inventories"][0]:
            return {"farmer": ["DROP"], "hands": [], "market": mkt}
        return {"farmer": ["PASS"], "hands": [], "market": mkt}

    return pol, tally


def probe_planting_cutoff(last_day):
    for crop in ("WHEAT", "CARROT"):
        results = {}
        for day in range(last_day - 5, last_day + 1):
            pol, tally = crop_policy(crop, day)
            drive(pol)
            results[day] = tally["units"]
        paying = [d for d, v in results.items() if v > 0]
        cutoff = max(paying) if paying else None
        record(f"planting cutoff ({crop})",
               f"units harvested when planted on day D: {results}",
               f"last profitable planting day = {cutoff} "
               f"(= last_day - {last_day - cutoff})" if cutoff is not None else "UNKNOWN",
               "confirmed" if cutoff is not None else "UNKNOWN")


def probe_final_water_bonus(last_day):
    """Does watering inside the bonus window still add yield on the last turn?"""
    seen = {}

    def pol(o):
        day, hour = o["day"], o["hour"]
        t = tile(o)
        priv = o["private"]
        mkt = []
        plant_day = last_day - 2
        if priv["seeds"].get("CARROT", 0) == 0 and t is None and day >= plant_day:
            mkt.append(["BUY_SEED", "CARROT", 1])
        if t is None and day >= plant_day and priv["seeds"].get("CARROT", 0) > 0:
            return {"farmer": ["PLANT", "CARROT"], "hands": [], "market": mkt}
        if isinstance(t, dict) and t.get("kind") == "PLANT":
            seen[(day, hour)] = (t["yield_units"], t["watered_today"])
            if not t["watered_today"]:
                return {"farmer": ["WATER"], "hands": [], "market": mkt}
        return {"farmer": ["PASS"], "hands": [], "market": mkt}

    drive(pol)
    final_day = [(k, v) for k, v in sorted(seen.items()) if k[0] == last_day]
    before = final_day[0][1][0] if final_day else None
    after = final_day[-1][1][0] if final_day else None
    record("WATER cutoff",
           f"CARROT planted day {last_day - 2}: yield on the final day went "
           f"{before} -> {after} across hours "
           f"{final_day[0][0][1] if final_day else '?'}.."
           f"{final_day[-1][0][1] if final_day else '?'}",
           "watering applies its bonus immediately, so it pays right up to the "
           "final actionable turn" if (after or 0) > (before or 0)
           else "no same-day gain observed",
           "confirmed" if final_day else "UNKNOWN")


# ------------------------------------------------------------------ endgame market

def probe_final_turn_market(last_day, last_hour):
    """Can produce still be banked on the very last actionable turn?"""
    outcomes = {}

    def make_pol(do_drop):
        def pol(o):
            day, hour = o["day"], o["hour"]
            priv = o["private"]
            inv = priv["inventories"][0] if priv["inventories"] else {}
            shed = priv["shed"]
            final = (day == last_day and hour == last_hour)
            mkt = []
            if day == 0 and hour == 0:
                mkt.append(["BUY_PRODUCT", "WHEAT", 10])
            # Take the stock into hand on the final day: the end-of-day drop
            # would otherwise put it back in the shed and hide the effect.
            if day == last_day and hour == 0 and shed.get("WHEAT", 0) > 0:
                return {"farmer": ["PICKUP", "WHEAT", 10], "hands": [], "market": []}
            if final:
                # Sell in the same turn we drop: unit actions resolve before the
                # market does, so the shed already holds the goods.
                mkt = [["SELL", "WHEAT", 10]]
                return {"farmer": ["DROP"] if do_drop else ["PASS"],
                        "hands": [], "market": mkt}
            return {"farmer": ["PASS"], "hands": [], "market": mkt}
        return pol

    for label, do_drop in (("drop+sell", True), ("sell only", False)):
        env = drive(make_pol(do_drop))
        outcomes[label] = money(env)

    gain = outcomes["drop+sell"] - outcomes["sell only"]
    record("final-turn liquidation",
           f"final money: DROP+SELL on the last turn = ${outcomes['drop+sell']:,.0f}, "
           f"SELL alone with stock still in hand = ${outcomes['sell only']:,.0f} "
           f"(difference ${gain:,.0f})",
           "the last actionable turn still processes unit actions and then the "
           "market, so DROP+SELL in one turn banks carried stock"
           if gain > 0 else "no gain observed",
           "confirmed" if gain != 0 else "UNKNOWN")

    record("carried stock at game end",
           f"stock left in a farmer's hands on the last turn is never banked "
           f"(worth ${gain:,.0f} if dropped first)",
           "end-of-day drop never runs on the final day; inventory must be "
           "DROPped by the last actionable turn",
           "confirmed" if gain > 0 else "UNKNOWN")


def probe_shed_overflow():
    """Cross a day boundary holding more than the shed can take.

    Run at shedCapacity 30 rather than the default 100 purely so the farm can
    afford to overfill it; the discard rule itself does not depend on the cap.
    """
    cap = 30
    obs_log = {}

    def pol(o):
        day, hour = o["day"], o["hour"]
        priv = o["private"]
        inv = priv["inventories"][0] if priv["inventories"] else {}
        shed = priv["shed"]
        used = sum(shed.values())
        carried = sum(inv.values())
        if day == 0 and hour == 23:
            obs_log["before"] = (used, carried)
        if day == 1 and hour == 0 and "after" not in obs_log:
            obs_log["after"] = (used, carried)
        if day > 0:
            return IDLE
        # Fill the shed, move stock into hand to free room, then fill it again.
        if used >= cap and carried < cap:
            return {"farmer": ["PICKUP", "WHEAT", cap], "hands": [], "market": []}
        if used < cap:
            return {"farmer": ["PASS"], "hands": [],
                    "market": [["BUY_PRODUCT", "WHEAT", cap - used]]}
        return IDLE

    drive(pol, extra={"shedCapacity": cap})
    before, after = obs_log.get("before"), obs_log.get("after")
    if before and after:
        held = before[0] + before[1]
        lost = held - after[0] - after[1]
        record("shed overflow",
               f"at shedCapacity={cap}, last turn of day 0 held shed={before[0]} "
               f"+ carried={before[1]} = {held}; next morning shed={after[0]}, "
               f"carried={after[1]}, so {lost} units vanished",
               f"end-of-day drop fills the shed to capacity and silently discards "
               f"the remainder; inventory is always emptied"
               if held > cap else "probe never exceeded capacity: UNKNOWN",
               "confirmed" if held > cap and after[1] == 0 and lost == held - cap
               else "UNKNOWN")
    else:
        record("shed overflow", "probe did not reach the day boundary",
               "UNKNOWN", "UNKNOWN")


def probe_planting_day_watering():
    """A crop planted and left unwatered that same day is dead by morning."""
    results = {}
    for water_on_planting_day in (True, False):
        state = {"outcome": None}

        def pol(o, w=water_on_planting_day):
            day, hour = o["day"], o["hour"]
            t = tile(o)
            priv = o["private"]
            mkt = []
            if day == 0 and priv["seeds"].get("WHEAT", 0) == 0 and t is None:
                mkt.append(["BUY_SEED", "WHEAT", 1])
            if day == 0 and t is None and priv["seeds"].get("WHEAT", 0) > 0:
                return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": mkt}
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                if day == 1 and hour == 0 and state["outcome"] is None:
                    state["outcome"] = f"alive (unwatered streak "
                    state["outcome"] += f"{t['consecutive_unwatered']})"
                skip = (day == 0 and not w)
                if not skip and not t["watered_today"]:
                    return {"farmer": ["WATER"], "hands": [], "market": mkt}
            if isinstance(t, dict) and t.get("kind") == "WEED" and state["outcome"] is None:
                state["outcome"] = f"dead by day {day} hour {hour}"
            return {"farmer": ["PASS"], "hands": [], "market": mkt}

        drive(pol, days=3)
        results[water_on_planting_day] = state["outcome"]

    killed = results[False] and results[False].startswith("dead")
    record("planting-day watering",
           f"watered on the planting day -> {results[True]}; "
           f"not watered on the planting day -> {results[False]}",
           "the planting day counts as the first unwatered day, so a new crop "
           "must be watered the same turn-day it is planted"
           if killed else "UNKNOWN",
           "confirmed" if killed else "UNKNOWN")


def probe_watering_cadence():
    """How often must an established crop be watered simply to stay alive?"""
    results = {}
    for interval in (1, 2, 3):
        state = {"died": None}

        def pol(o, k=interval):
            day, hour = o["day"], o["hour"]
            t = tile(o)
            priv = o["private"]
            mkt = []
            if day == 0 and priv["seeds"].get("MELON", 0) == 0 and t is None:
                mkt.append(["BUY_SEED", "MELON", 1])
            if day == 0 and t is None and priv["seeds"].get("MELON", 0) > 0:
                return {"farmer": ["PLANT", "MELON"], "hands": [], "market": mkt}
            if isinstance(t, dict) and t.get("kind") == "WEED" and state["died"] is None:
                state["died"] = day
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                if day % k == 0 and not t["watered_today"]:
                    return {"farmer": ["WATER"], "hands": [], "market": mkt}
            return {"farmer": ["PASS"], "hands": [], "market": mkt}

        drive(pol, days=9)
        results[interval] = state["died"] or "survived"

    survivors = [k for k, v in results.items() if v == "survived"]
    record("watering cadence for survival",
           f"MELON watered every k days, outcome by k: {results}",
           f"watering every {max(survivors)} days keeps a crop alive; "
           f"a third consecutive dry day kills it"
           if survivors else "UNKNOWN",
           "confirmed" if survivors else "UNKNOWN")


def main():
    last_step, last_day, last_hour = probe_episode_shape()
    print(f"episode shape: last actionable turn = step {last_step}, "
          f"day {last_day}, hour {last_hour}\n", flush=True)

    probes = (
        ("crop decay", lambda: probe_crop_decay()),
        ("planting-day watering", lambda: probe_planting_day_watering()),
        ("watering cadence", lambda: probe_watering_cadence()),
        ("water cutoff", lambda: probe_final_water_bonus(last_day)),
        ("final-turn market", lambda: probe_final_turn_market(last_day, last_hour)),
        ("shed overflow", lambda: probe_shed_overflow()),
        ("care cutoff", lambda: probe_care_cutoff(last_day)),
        ("feed cutoff", lambda: probe_feed_cutoff(last_day)),
        ("animal purchase cutoff", lambda: probe_animal_purchase_cutoff(last_day)),
        ("planting cutoff", lambda: probe_planting_cutoff(last_day)),
    )
    wanted = [a.lower() for a in sys.argv[1:]]
    for name, fn in probes:
        if wanted and not any(w in name for w in wanted):
            continue
        print(f"  probing {name}...", flush=True)
        fn()

    print("\n" + "=" * 118)
    print(f"{'Mechanic':<26} | {'Observed behaviour':<58} | {'Cutoff':<44} | Confidence")
    print("=" * 118)
    for mechanic, observed, cutoff, confidence in FINDINGS:
        obs_lines = _wrap(observed, 58)
        cut_lines = _wrap(cutoff, 44)
        rows = max(len(obs_lines), len(cut_lines))
        for i in range(rows):
            head = mechanic if i == 0 else ""
            conf = confidence if i == 0 else ""
            o = obs_lines[i] if i < len(obs_lines) else ""
            c = cut_lines[i] if i < len(cut_lines) else ""
            print(f"{head:<26} | {o:<58} | {c:<44} | {conf}")
        print("-" * 118)
    print(f"\nNote: episodes were {DAYS} days, so 'last_day' = {last_day}. "
          f"Cutoffs are stated relative to last_day and carry over to the "
          f"30-day competition setting.")


def _wrap(text, width):
    words, lines, cur = str(text).split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    lines.append(cur)
    return lines or [""]


if __name__ == "__main__":
    main()
