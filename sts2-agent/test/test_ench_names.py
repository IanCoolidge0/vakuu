"""Enchantment bracket display names ('Strike[Sharp 2]') and the play_card
name-resolution ladder that makes specific copies addressable."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handlers.formatters import card_display_name, format_combat
from agent import Agent

SHARP = {"name": "Strike", "cost": 1, "type": "attack", "upgraded": False,
         "description": "Deal 8 damage.",
         "enchantment": {"name": "Sharp", "amount": 2, "disabled": False,
                         "description": "Increases damage on this card by 2."}}
PLAIN = {"name": "Strike", "cost": 1, "type": "attack", "upgraded": False,
         "description": "Deal 6 damage."}
GLAM_SPENT = {"name": "Twin Strike", "cost": 1, "type": "attack", "upgraded": False,
              "description": "Deal 3 damage twice.",
              "enchantment": {"name": "Glam", "disabled": True,
                              "description": "This card has Replay one per combat."}}
POMMEL_UP = {"name": "Pommel Strike", "cost": 1, "type": "attack", "upgraded": True,
             "description": "Deal 10 damage. Draw 2 cards."}
HAND = [SHARP, PLAIN, GLAM_SPENT, POMMEL_UP]


def main():
    assert card_display_name(SHARP) == "Strike[Sharp 2]"
    assert card_display_name(PLAIN) == "Strike"
    assert card_display_name(GLAM_SPENT) == "Twin Strike[Glam(disabled)]"
    assert card_display_name(POMMEL_UP) == "Pommel Strike+"

    agent = Agent.__new__(Agent)
    agent.client = MagicMock()
    agent.client.get_combat.return_value = {"hand": HAND}

    cases = [
        ("Strike[Sharp 2]", 0),           # exact enchanted copy
        ("Strike", 1),                    # bare name -> exact display = plain copy
        ("strike [sharp 2]", 0),          # spacing/case tolerated
        ("Twin Strike[Glam(disabled)]", 2),
        ("Twin Strike", 2),               # bracket-stripped match
        ("Pommel Strike+", 3),
        ("Pommel Strike", 3),             # base name
        ("Bash", None),                   # not in hand
    ]
    for req, want in cases:
        got = agent._resolve_card_index(req)
        assert got == want, f"{req!r}: got {got}, want {want}"
    print("resolution ladder OK")

    # Only-enchanted-copy present: bare name still resolves to it
    agent.client.get_combat.return_value = {"hand": [SHARP, GLAM_SPENT]}
    assert agent._resolve_card_index("Strike") == 0
    print("bare-name fallback OK")

    # Hand report speaks the same vocabulary as the prompts
    agent.client.get_combat.return_value = {"hand": HAND}
    assert agent._hand_names() == ["Strike[Sharp 2]", "Strike",
                                   "Twin Strike[Glam(disabled)]", "Pommel Strike+"]
    print("hand report OK")

    # Combat prompt: bracket names in hand lines, definitions at the end,
    # old {Enchanted...} suffix gone
    state = {"screen": "combat", "ascension": 0}
    combat = {"turn": 2, "energy": 3, "max_energy": 3,
              "player": {"hp": 80, "max_hp": 80, "block": 0, "powers": []},
              "enemies": [], "hand": HAND,
              "draw_pile_count": 0, "discard_pile_count": 0, "exhaust_pile_count": 0,
              "potions": [], "relics": []}
    out = format_combat(state, combat)
    assert "[0] Strike[Sharp 2] (cost 1) [attack] - Deal 8 damage." in out
    assert "ENCHANTMENTS:" in out
    assert "Sharp 2: Increases damage on this card by 2." in out
    assert "Glam(disabled): This card has Replay one per combat." in out
    assert "{Enchanted" not in out
    print("combat prompt OK")


if __name__ == "__main__":
    main()
