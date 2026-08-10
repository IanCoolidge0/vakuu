"""Keyword tags and enchantment rendering in prompts, plus bare-name
enchantment mentions in event text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handlers.formatters import card_tags, card_display_name, format_event, format_combat

STATE = {"screen": "combat", "character": "The Ironclad", "ascension": 0, "act": 1,
         "floor": 2, "hp": 80, "max_hp": 80, "gold": 99, "relics": [], "potions": []}


def main():
    plain = {"name": "Strike", "cost": 1, "type": "attack",
             "description": "Deal 6 damage.", "upgraded": False}
    wound = dict(plain, name="Wound", type="status", cost=-1, description="",
                 keywords=["Unplayable"])
    glam = dict(plain, name="Twin Strike", description="Deal 3 damage twice.",
                enchantment={"name": "Glam",
                             "description": "This card has Replay one per combat."})

    # Keyword flags fold into the type bracket (they are NOT in description text)
    assert card_tags(plain) == "[attack]"
    assert card_tags(wound) == "[status, Unplayable]"
    assert card_display_name(glam) == "Twin Strike[Glam]"

    # Combat prompt end-to-end: bracket names, keyword tags, definitions section
    combat = {"turn": 2, "energy": 3, "max_energy": 3,
              "player": {"hp": 80, "max_hp": 80, "block": 0, "powers": []},
              "enemies": [], "hand": [glam, wound],
              "draw_pile_count": 3, "discard_pile_count": 0, "exhaust_pile_count": 0,
              "potions": [], "relics": []}
    out = format_combat(STATE, combat)
    assert "Twin Strike[Glam]" in out
    assert "[status, Unplayable]" in out
    assert "ENCHANTMENTS:" in out and "Glam: This card has Replay one per combat." in out
    print("combat prompt OK")

    # Event bare-name mentions: Glam defined; 'Swift Potion' must not trigger 'Swift'
    event = {"name": "Neow", "body": None, "options": [
        {"index": 0, "label": "Silken Tress", "is_locked": False,
         "description": "Lose all Gold. Enchant all cards in the first card reward with Glam."},
        {"index": 1, "label": "Flask", "is_locked": False,
         "description": "Obtain a Swift Potion."},
    ]}
    out = format_event(dict(STATE, screen="event", event=event))
    assert "Glam: This card has Replay once per combat" in out, out
    assert "Swift:" not in out, out
    print("event mentions OK")


if __name__ == "__main__":
    main()
