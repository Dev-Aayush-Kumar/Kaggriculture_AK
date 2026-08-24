"""E56 - economic composition of existing H4 traces, plus one live wheat ledger.

No strategy change. Probe sell_events omit WHEAT, so a one-seed wrapper
counts BUY/SELL/PICKUP wheat the executor actually asked for.
"""

import json
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import baselines as B  # noqa: E402
import harness as H  # noqa: E402
from kagg.agent import Executor  # noqa: E402
from kagg.config import Config  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RESULTS = os.path.join(ROOT, "results")

H4 = dict(B.P1_S, harvest_defer_enabled=True, harvest_defer_wool_only=True,
          endgame_rescue_feed=True)

ITEMS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
         "EGG", "MILK", "WOOL", "FERTILIZER"]


def load(name):
    path = os.path.join(RESULTS, name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seats(recs, name):
    return [(r, s, r["players"][s]) for r in recs for s in (0, 1)
            if r["players"][s]["name"] == name]


def fmean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else 0.0


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0
    k = min(len(s) - 1, max(0, int(q * len(s)) - (0 if q == 0 else 1)))
    return s[k]


def show_rev(label, rows):
    print(f"\n{label} n={len(rows)} mean quote-rev / harvested / sold / floor")
    total = 0
    for it in ITEMS:
        rev = fmean(p.get("sell_revenue", {}).get(it, 0) for _, _, p in rows)
        har = fmean(p.get("harvested", {}).get(it, 0) for _, _, p in rows)
        sold = fmean(p.get("sell_requested", {}).get(it, 0) for _, _, p in rows)
        fl = fmean(p.get("sell_floor_units", {}).get(it, 0) for _, _, p in rows)
        if rev or har or sold:
            px = rev / sold if sold else 0
            total += rev
            print(f"  {it:<12} rev={rev:8.0f}  h={har:6.1f}  sold={sold:6.1f}  "
                  f"floor={fl:5.1f}  px={px:6.1f}")
    print(f"  TOTAL quote-rev {total:,.0f}")


class WheatLedger:
    """Count the executor's wheat orders and pickups. Does not change actions."""

    def __init__(self, fn):
        self.fn = fn
        self.buy_qty = 0
        self.sell_qty = 0
        self.pickup_qty = 0
        self.pickup_n = 0
        self.feed_n = 0
        self.buy_orders = 0
        self.pickup_hist = Counter()
        self.day0_orders = None
        self.money_day = []

    def __call__(self, obs, configuration=None):
        action = self.fn(obs, configuration)
        if obs["day"] == 0 and obs["hour"] == 0:
            self.day0_orders = list(action.get("market") or [])
        if obs["hour"] == 0:
            self.money_day.append(obs["farms"][obs["player"]]["money"])
        for order in action.get("market") or []:
            if not order:
                continue
            if order[0] == "BUY_PRODUCT" and order[1] == "WHEAT":
                self.buy_qty += order[2]
                self.buy_orders += 1
            elif order[0] == "SELL" and order[1] == "WHEAT":
                self.sell_qty += order[2]
        units = [action.get("farmer", ["PASS"])]
        units.extend(action.get("hands") or [])
        for act in units:
            if not act:
                continue
            if act[0] == "PICKUP" and len(act) >= 3 and act[1] == "WHEAT":
                self.pickup_qty += act[2]
                self.pickup_n += 1
                self.pickup_hist[act[2]] += 1
            elif act[0] == "FEED":
                self.feed_n += 1
        return action


def live_wheat():
    print("\n======== E56 live wheat ledger: 1 seed H4 vs P1-S, both seats ========")
    h4 = WheatLedger(Executor(Config(**H4)))
    p1s = Executor(Config(**dict(B.P1_S)))
    rec = H.play(( "H4", h4), ("P1S", p1s), seed=0)
    p = rec["players"][0]
    print(f"money H4={rec['money'][0]:.0f} P1S={rec['money'][1]:.0f} "
          f"winner={rec['winner']}")
    print(f"harvested wheat={p.get('harvested', {}).get('WHEAT', 0)}")
    print(f"probe sell_requested wheat={p.get('sell_requested', {}).get('WHEAT', 0)}")
    print(f"probe sell_revenue wheat={p.get('sell_revenue', {}).get('WHEAT', 0):.0f}")
    print(f"asked BUY_PRODUCT WHEAT qty={h4.buy_qty} orders={h4.buy_orders}")
    print(f"asked SELL WHEAT qty={h4.sell_qty}")
    print(f"asked PICKUP WHEAT qty={h4.pickup_qty} n={h4.pickup_n} hist={dict(h4.pickup_hist)}")
    print(f"FEED actions={h4.feed_n}")
    print(f"net wheat to market (sell-buy)={h4.sell_qty - h4.buy_qty}")
    print(f"pickup per feed={h4.pickup_qty / h4.feed_n if h4.feed_n else 0:.2f}")
    print(f"day0 orders: {h4.day0_orders}")
    print(f"money_by_day[:8]={ [round(x,1) for x in h4.money_day[:8]] }")
    print(f"animals_by_day[:10]={p.get('animals_by_day', [])[:10]}")
    print(f"feed_pickup_qty current = n_animals (not capped)")


def e55():
    print("======== E55 SCREEN (existing runs) ========")
    pairs = [
        ("e55-r280-h4-20260824-202606.json", "R280", "H4"),
        ("e55-r280-p1s-20260824-202958.json", "R280", "P1S"),
        ("e55-r0-h4-20260824-203319.json", "R0", "H4"),
        ("e55-r0-p1s-20260824-203532.json", "R0", "P1S"),
        ("e55-fert-h4-20260824-203844.json", "FERT", "H4"),
        ("e55-fert-p1s-20260824-203953.json", "FERT", "P1S"),
    ]
    for path, a, b in pairs:
        recs = load(path)
        for name in (a, b):
            rows = seats(recs, name)
            wins = sum(1 for r, s, _ in rows if r["winner"] == s)
            losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
            money = [r["money"][s] for r, s, _ in rows]
            esc = fmean(p.get("animals_escaped", 0) for _, _, p in rows)
            print(f"  {os.path.basename(path)[:22]:<22} {name:<5} "
                  f"{wins:>2}-{losses:<2} mean={fmean(money):7,.0f} "
                  f"p10={pct(money, 0.1):7,.0f} esc={esc:.2f}")


def e50():
    recs = load("e50-h4-p1s-20260824-041910.json")
    print("\n======== E50 H4 vs P1-S ========")
    for name in ("H4", "P1S"):
        rows = seats(recs, name)
        wins = sum(1 for r, s, _ in rows if r["winner"] == s)
        losses = sum(1 for r, s, _ in rows if r["winner"] == 1 - s)
        money = [r["money"][s] for r, s, _ in rows]
        print(f"{name}: {wins}-{losses}-{len(rows)-wins-losses} "
              f"P(win)={wins/len(rows):.3f} mean={fmean(money):,.0f} "
              f"p10={pct(money, 0.1):,.0f}")
        print(f"  drought={fmean(p['drought_deaths'] for _,_,p in rows):.2f} "
              f"escaped={fmean(p['animals_escaped'] for _,_,p in rows):.2f} "
              f"idle={fmean(p.get('category_share',{}).get('idle',0) for _,_,p in rows):.3f}")
        show_rev(name, rows)
        print(f"  BUY_PRODUCT orders={fmean(p.get('market_ops',{}).get('BUY_PRODUCT',0) for _,_,p in rows):.1f}")
        print(f"  PICKUP={fmean(p.get('ops',{}).get('PICKUP',0) for _,_,p in rows):.1f} "
              f"FEED={fmean(p.get('ops',{}).get('FEED',0) for _,_,p in rows):.1f}")
        print(f"  money_by_day[:8] mean="
              f"{[round(fmean(p['money_by_day'][d] for _,_,p in rows if len(p.get('money_by_day') or [])>d),1) for d in range(8)]}")
        print(f"  animals_by_day[:10] mean="
              f"{[round(fmean((p.get('animals_by_day') or [0])[d] if d < len(p.get('animals_by_day') or []) else 0 for _,_,p in rows),2) for d in range(10)]}")


def main():
    e55()
    e50()
    live_wheat()
    print("\nE56 FACTS")
    print("  E55 R280/R0/FERT do not beat H4. Third-sheep reserve and")
    print("  fertilize_crops are closed as P(win) improvements.")
    print("  E50 wheat quote-sold is ~3x harvested; BUY_PRODUCT is frequent;")
    print("  day-1 cash is ~$160. Live ledger reports the actual wheat buy/sell.")


if __name__ == "__main__":
    main()
