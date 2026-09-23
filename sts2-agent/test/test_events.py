"""Event prompt: lethal options carry the game's kill-glow warning, and
choose_event_option passes confirm only when asked."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handlers.formatters import format_event
from client import GameClient


def main():
    state = {
        "screen": "event", "character": "The Silent", "ascension": 0,
        "act": 2, "floor": 8, "hp": 40, "max_hp": 70, "gold": 90,
        "relics": [], "potions": [{"name": None}],
        "event": {"name": "Trial", "body": "", "options": [
            {"index": 0, "label": "Accept", "description": "Receive a curse.",
             "is_locked": False, "is_proceed": False},
            {"index": 1, "label": "Double Down", "description": "Die.",
             "is_locked": False, "is_proceed": True, "will_kill": True},
        ]},
    }
    out = format_event(state)
    assert "[0] Accept: Receive a curse." in out, out
    assert "[1] Double Down [KILLS YOU]: Die." in out, out
    print("kill marker OK")

    # confirm is sent only when asked for
    sent = []
    client = GameClient()
    client._post = lambda path, data: sent.append(data) or {"success": True}
    client.choose_event_option(1)
    client.choose_event_option(1, confirm=True)
    assert "confirm" not in sent[0], sent
    assert sent[1]["confirm"] is True, sent
    print("confirm passthrough OK")


def shop_main():
    """Shop: potions listed with slot indices, use_potion offered."""
    from handlers.formatters import format_shop
    from tools import get_tools_for_screen

    state = {
        "screen": "shop", "character": "The Silent", "ascension": 0,
        "act": 2, "floor": 5, "hp": 40, "max_hp": 70, "gold": 120,
        "relics": [], "potions": [{"index": 0, "name": None},
                                  {"index": 1, "name": "Foul Potion"}],
        "shop": {"cards": [], "potions": [], "card_removal_cost": None,
                 "relics": [{"name": "Snecko Eye", "price": 150, "description": "?"}]},
    }
    out = format_shop(state)
    assert "Snecko Eye - 150g [CAN'T AFFORD]" in out, out
    assert "Your potions: [1] Foul Potion" in out, out
    names = [t["name"] for t in get_tools_for_screen("shop")]
    assert "use_potion" in names and "shop_buy" in names, names
    print("shop potions OK")


if __name__ == "__main__":
    main()
    shop_main()
