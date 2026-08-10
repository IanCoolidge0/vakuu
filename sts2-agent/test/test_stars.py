"""Regent Stars: combined energy+star cost rendering, the [S] icon
convention in card text, and the Stars line in the combat header."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handlers.formatters import fmt_card_cost, clean_desc, format_combat

STAR = "res://images/packed/sprite_fonts/star_icon.png"
ENERGY = "res://images/packed/sprite_fonts/ironclad_energy_icon.png"


def main():
    # Cost rendering
    assert fmt_card_cost({"cost": 1}) == "1"
    assert fmt_card_cost({"cost": -1}) == "X"
    assert fmt_card_cost({"cost": 1, "star_cost": None}) == "1"
    assert fmt_card_cost({"cost": 1, "star_cost": 2}) == "1+2S"
    assert fmt_card_cost({"cost": 0, "star_cost": 3}) == "0+3S"
    assert fmt_card_cost({"cost": 2, "star_cost": -1}) == "2+XS"
    assert fmt_card_cost({"cost": -1, "star_cost": 1}) == "X+1S"
    print("fmt_card_cost OK")

    # [S] icon convention alongside [E]; star icons survive the generic strip
    assert clean_desc(f"Gain {STAR}{STAR}.") == "Gain [S][S]."
    assert clean_desc(f"Gain {ENERGY} and {STAR}.") == "Gain [E] and [S]."
    print("[S] sanitizer OK")

    # Combat header: Stars line appears when nonzero, or when a star-cost
    # card is in hand (zero is then load-bearing); absent otherwise
    def combat(stars, hand):
        return {"turn": 1, "energy": 3, "max_energy": 3, "stars": stars,
                "player": {"hp": 70, "max_hp": 70, "block": 0, "powers": []},
                "enemies": [], "hand": hand,
                "draw_pile_count": 0, "discard_pile_count": 0,
                "exhaust_pile_count": 0, "potions": [], "relics": []}

    state = {"screen": "combat", "ascension": 0}
    starcard = {"name": "Falling Star", "cost": 0, "star_cost": 2, "type": "attack",
                "upgraded": False, "description": "Deal 12 damage."}
    plain = {"name": "Strike", "cost": 1, "type": "attack", "upgraded": False,
             "description": "Deal 6 damage."}

    out = format_combat(state, combat(4, [plain]))
    assert "Stars: 4" in out
    out = format_combat(state, combat(0, [starcard]))
    assert "Stars: 0" in out
    assert "Falling Star (cost 0+2S) [attack]" in out
    out = format_combat(state, combat(0, [plain]))
    assert "Stars:" not in out
    # Old-mod payloads without a stars key degrade cleanly
    c = combat(0, [plain]); del c["stars"]
    assert "Stars:" not in format_combat(state, c)
    print("combat header OK")


if __name__ == "__main__":
    main()
