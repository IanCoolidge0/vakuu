"""Power descriptions: the POWER EFFECTS section of the combat prompt,
built from the tooltip text the mod now sends with each power."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handlers.formatters import power_definitions_section, format_combat


def combat(player_powers, enemies):
    return {"turn": 2, "energy": 3, "max_energy": 3, "stars": 0,
            "player": {"name": "The Silent", "hp": 40, "max_hp": 70, "block": 0,
                       "powers": player_powers},
            "osty": {"hp": -1, "max_hp": -1, "block": -1, "is_alive": False},
            "orb_slots": 0, "orbs": [],
            "enemies": enemies, "hand": [],
            "draw_pile_count": 0, "discard_pile_count": 0,
            "exhaust_pile_count": 0, "potions": [], "relics": []}


def enemy(index, name, powers, is_dead=False):
    return {"index": index, "name": name, "hp": 10, "max_hp": 10, "block": 0,
            "intents": [], "powers": powers, "is_dead": is_dead}


def main():
    ringing = {"name": "Ringing", "amount": 1,
               "description": "You can only play 1 card this turn."}
    slippery = {"name": "Slippery", "amount": 1,
                "description": "The next time this creature would take damage, it takes 1 instead."}

    c = combat([ringing], [enemy(0, "Inklet", [slippery]),
                           enemy(1, "Inklet", [slippery])])
    out = power_definitions_section(c)
    assert out.startswith("POWER EFFECTS:"), out
    assert "  Ringing: You can only play 1 card this turn." in out
    # Identical debuffs on several enemies are listed once
    assert out.count("Slippery:") == 1, out
    print("dedupe OK")

    # Same power, different resolved text (amounts) -> both listed
    str2 = {"name": "Strength", "amount": 2, "description": "Increases attack damage by 2."}
    str5 = {"name": "Strength", "amount": 5, "description": "Increases attack damage by 5."}
    out = power_definitions_section(combat([str2], [enemy(0, "Nibbit", [str5])]))
    assert out.count("Strength:") == 2, out
    print("per-amount lines OK")

    # Dead enemies' powers and description-less payloads (older mods) are skipped
    old = {"name": "Weak", "amount": 1}
    out = power_definitions_section(combat([old], [enemy(0, "Gone", [slippery], is_dead=True)]))
    assert out == "", out
    print("skips OK")

    # Wired into the combat prompt
    out = format_combat({"screen": "combat", "ascension": 0}, combat([ringing], []))
    assert "POWER EFFECTS:" in out and "Ringing: You can only play 1 card" in out
    print("combat prompt OK")


if __name__ == "__main__":
    main()
