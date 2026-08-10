"""Agent._state_fingerprint: detects whether a fire-and-forget action
actually changed the observable game state (settle logic)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Agent

fp = Agent._state_fingerprint

BASE = {
    "screen": "rewards", "hp": 51, "max_hp": 80, "gold": 63, "floor": 7, "act": 1,
    "potions": [{"name": None}, {"name": "Strength Potion"}, {"name": None}],
    "relics": [{"name": "Burning Blood"}, {"name": "Lava Rock"}],
    "rewards": {"rewards": [{"type": "gold"}, {"type": "potion"},
                            {"type": "relic"}, {"type": "card"}]},
}


def main():
    # Gold claim: gold + rewards list change
    after_gold = dict(BASE, gold=107,
                      rewards={"rewards": [{"type": "potion"}, {"type": "relic"},
                                           {"type": "card"}]})
    assert fp(BASE) != fp(after_gold), "gold claim not observed"

    # Identical state -> identical fingerprint
    assert fp(BASE) == fp(dict(BASE)), "identical state produced diff"

    # Event options draining (a stuck event's closing proceed) is observed
    ev1 = {"screen": "map", "hp": 78, "gold": 63,
           "event": {"name": "Aroma of Chaos", "options": [{"label": "Continue"}]}}
    ev2 = {"screen": "map", "hp": 78, "gold": 63,
           "event": {"name": "Aroma of Chaos", "options": []}}
    assert fp(ev1) != fp(ev2), "event option drain not observed"

    # Rest heal
    assert fp(dict(BASE, hp=80)) != fp(BASE), "heal not observed"

    # Missing keys tolerated
    assert fp({}) == fp({}), "empty state unstable"
    print("fingerprint OK")


if __name__ == "__main__":
    main()
