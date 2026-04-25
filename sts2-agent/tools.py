"""Tool definitions for LLM function calling. Each tool maps to a game API action."""

COMBAT_TOOLS = [
    {
        "name": "play_card",
        "description": "Play a card from your hand by name. If you have multiple copies, the first one is played. Attack cards that deal damage to a single enemy require target_index.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_name": {
                    "type": "string",
                    "description": "Name of the card to play (e.g. 'Strike', 'Bash', 'Defend')"
                },
                "target_index": {
                    "type": "integer",
                    "description": "Index of the enemy to target (0-based). Required for single-target attack cards."
                },
            },
            "required": ["card_name"]
        }
    },
    {
        "name": "end_turn",
        "description": "End your turn. The enemy will take their turn, then you draw a new hand and regain energy.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "use_potion",
        "description": "Use a potion from your potion slots. Some potions require a target.",
        "input_schema": {
            "type": "object",
            "properties": {
                "potion_index": {
                    "type": "integer",
                    "description": "Index of the potion slot (0-based)"
                },
                "target_index": {
                    "type": "integer",
                    "description": "Index of the enemy to target (0-based). Required for potions that target an enemy."
                }
            },
            "required": ["potion_index"]
        }
    },
]

MAP_TOOLS = [
    {
        "name": "choose_map_node",
        "description": "Choose the next node on the map to travel to. You can only move to nodes connected to your current position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "col": {"type": "integer", "description": "Column of the map node"},
                "row": {"type": "integer", "description": "Row of the map node"}
            },
            "required": ["col", "row"]
        }
    },
]

EVENT_TOOLS = [
    {
        "name": "choose_event_option",
        "description": "Choose an option in the current event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "option_index": {
                    "type": "integer",
                    "description": "Index of the event option (0-based)"
                }
            },
            "required": ["option_index"]
        }
    },
]

CARD_REWARD_TOOLS = [
    {
        "name": "choose_card_reward",
        "description": "Pick a card to add to your deck from the card reward options.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_index": {
                    "type": "integer",
                    "description": "Index of the card to pick (0-based)"
                }
            },
            "required": ["card_index"]
        }
    },
    {
        "name": "skip_card_reward",
        "description": "Skip the card reward without adding any card to your deck.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]

REWARDS_TOOLS = [
    {
        "name": "claim_reward",
        "description": "Claim a reward from the rewards screen by type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reward_type": {
                    "type": "string",
                    "enum": ["gold", "card", "potion", "relic", "remove_card", "special_card"],
                    "description": "Type of the reward to claim"
                }
            },
            "required": ["reward_type"]
        }
    },
]

TREASURE_TOOLS = [
    {
        "name": "open_chest",
        "description": "Open the treasure chest. Use this when chest_state is 'closed'. Reveals the relic inside.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "pick_relic",
        "description": "Take a relic from the opened chest. Use this when chest_state is 'open'. Defaults to the first available relic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "Index of the relic to pick (0-based). Optional; defaults to 0 (the first/only relic)."
                }
            },
            "required": []
        }
    },
]

REST_TOOLS = [
    {
        "name": "choose_rest_option",
        "description": "Choose a rest site option (Rest to heal, Smith to upgrade a card, etc). If you choose Smith, a card selection screen will open to pick which card to upgrade.",
        "input_schema": {
            "type": "object",
            "properties": {
                "option_index": {
                    "type": "integer",
                    "description": "Index of the rest option (0-based)"
                }
            },
            "required": ["option_index"]
        }
    },
]

SHOP_TOOLS = [
    {
        "name": "shop_buy",
        "description": "Buy an item from the shop. The index refers to the position among all stocked items (cards first, then relics, then potions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_index": {
                    "type": "integer",
                    "description": "Index of the shop item to buy (0-based among stocked items)"
                }
            },
            "required": ["slot_index"]
        }
    },
    {
        "name": "shop_remove_card",
        "description": "Pay to remove a card from your deck at the shop. Opens a card selection screen where you pick which card to remove.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]

# Utility tools available on all screens
UTILITY_TOOLS = [
    {
        "name": "proceed",
        "description": "Leave the current room/screen by clicking its proceed button. Use this when you're done with the current screen — this includes leaving a shop with items you don't want, skipping remaining rewards, exiting a rest site after resting, or continuing after an event. Also works as an escape hatch if the screen is stuck (e.g. map clicks not registering after an event). Don't call this in the middle of combat or when you still want to take an action on the current screen.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "view_deck",
        "description": "View your full deck (sorted alphabetically). Useful before making upgrade, remove, or card reward decisions.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "view_map",
        "description": "View the full map with all nodes and connections. Useful for planning your path.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "view_draw_pile",
        "description": "View your draw pile, discard pile, and exhaust pile. Only available during combat.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


HAND_SELECT_TOOLS = [
    {
        "name": "select_hand_card",
        "description": "Select a card for the pending card selection prompt. The trigger card's description tells you what will happen to the selected card (e.g. upgrade, discard, exhaust).",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_name": {
                    "type": "string",
                    "description": "Name of the card to select from the available options"
                }
            },
            "required": ["card_name"]
        }
    },
]

CARD_SELECT_TOOLS = [
    {
        "name": "select_card",
        "description": "Select a card from the grid (e.g. to upgrade, transform, or remove).",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_index": {
                    "type": "integer",
                    "description": "Index of the card to select (0-based)"
                }
            },
            "required": ["card_index"]
        }
    },
    {
        "name": "confirm_selection",
        "description": "Confirm your card selection (after selecting a card to upgrade/transform/remove).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


def get_tools_for_screen(screen: str) -> list[dict]:
    """Return the appropriate tool set for the current game screen."""
    tools = list(UTILITY_TOOLS)

    match screen:
        case "combat":
            tools.extend(COMBAT_TOOLS)
        case "map":
            tools.extend(MAP_TOOLS)
        case "event" | "ancient":
            tools.extend(EVENT_TOOLS)
        case "card_reward":
            tools.extend(CARD_REWARD_TOOLS)
        case "rewards":
            tools.extend(REWARDS_TOOLS)
        case "rest":
            tools.extend(REST_TOOLS)
        case "shop":
            tools.extend(SHOP_TOOLS)
        case "treasure":
            tools.extend(TREASURE_TOOLS)
        case "hand_select":
            tools.extend(HAND_SELECT_TOOLS)
        case "card_select":
            tools.extend(CARD_SELECT_TOOLS)

    return tools
