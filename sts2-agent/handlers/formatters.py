"""Format game state into readable text for the LLM."""

import json


def format_combat(state: dict, combat: dict) -> str:
    lines = [
        f"=== COMBAT (Turn {combat['turn']}) ===",
        f"Energy: {combat['energy']}/{combat['max_energy']}",
        f"HP: {combat['player']['hp']}/{combat['player']['max_hp']} | Block: {combat['player']['block']}",
    ]

    if combat['player']['powers']:
        powers = ", ".join(f"{p['name']}({p['amount']})" for p in combat['player']['powers'])
        lines.append(f"Your powers: {powers}")

    lines.append("")
    lines.append("ENEMIES:")
    for e in combat['enemies']:
        if e['is_dead']:
            continue
        intents = ", ".join(
            f"{i['type']}" + (f" {i['damage']}x{i['hits']}" if i.get('damage') else "")
            for i in e['intents']
        )
        enemy_line = f"  [{e['index']}] {e['name']} HP:{e['hp']}/{e['max_hp']} Block:{e['block']} Intent:[{intents}]"
        if e['powers']:
            powers = ", ".join(f"{p['name']}({p['amount']})" for p in e['powers'])
            enemy_line += f" Powers:[{powers}]"
        lines.append(enemy_line)

    lines.append("")
    lines.append("YOUR HAND:")
    for i, c in enumerate(combat['hand']):
        upgraded = "+" if c['upgraded'] else ""
        lines.append(f"  [{i}] {c['name']}{upgraded} (cost {c['cost']}) [{c['type']}] - {c['description']}")

    lines.append("")
    lines.append(f"Draw pile: {combat['draw_pile_count']} | Discard: {combat['discard_pile_count']} | Exhaust: {combat['exhaust_pile_count']}")

    lines.append("")
    lines.append("POTIONS:")
    for p in combat['potions']:
        lines.append(f"  [{p['index']}] {p['name'] or '(empty)'}")

    lines.append("")
    lines.append("RELICS:")
    for r in combat['relics']:
        counter = f" [{r['counter']}]" if r.get('counter') is not None else ""
        lines.append(f"  {r['name']}{counter}")

    return "\n".join(lines)


def format_state(state: dict) -> str:
    lines = [
        f"=== {state['screen'].upper()} ===",
        f"{state['character']} | Ascension {state['ascension']} | Act {state['act']} Floor {state['floor']}",
        f"HP: {state['hp']}/{state['max_hp']} | Gold: {state['gold']}",
    ]

    lines.append("Relics: " + ", ".join(
        r['name'] + (f" [{r['counter']}]" if r.get('counter') is not None else "")
        for r in state['relics']
    ))
    lines.append("Potions: " + ", ".join(
        p['name'] or '(empty)' for p in state['potions']
    ))

    return "\n".join(lines)


def format_event(state: dict) -> str:
    lines = [format_state(state)]
    event = state['event']
    lines.append(f"\nEvent: {event['name']}")
    if event['body']:
        lines.append(f"\n{event['body']}")
    lines.append("\nOptions:")
    for o in event['options']:
        locked = " [LOCKED]" if o['is_locked'] else ""
        lines.append(f"  [{o['index']}] {o['label']}{locked}: {o['description']}")
    return "\n".join(lines)


def format_card_reward(state: dict) -> str:
    lines = [format_state(state)]
    lines.append("\nChoose a card to add to your deck (or skip):")
    for i, c in enumerate(state['card_reward']['cards']):
        upgraded = "+" if c['upgraded'] else ""
        lines.append(f"  [{i}] {c['name']}{upgraded} (cost {c['cost']}) [{c['type']}] - {c['description']}")
    return "\n".join(lines)


def format_rewards(state: dict) -> str:
    lines = [format_state(state)]
    rewards = state['rewards']['rewards']
    if rewards:
        lines.append(f"\nRewards available ({len(rewards)}):")
        lines.append("Claim each reward, then proceed when done.")
        for i, r in enumerate(rewards):
            lines.append(f"  [{i}] {r['type']}: {r['description']}")
    else:
        lines.append("\nAll rewards claimed. Proceed to continue.")
    return "\n".join(lines)


def format_rest(state: dict) -> str:
    lines = [format_state(state)]
    lines.append("\nRest site options:")
    for i, o in enumerate(state['rest_site']['options']):
        enabled = "" if o['is_enabled'] else " [DISABLED]"
        lines.append(f"  [{i}] {o['label']}{enabled}: {o['description']}")
    return "\n".join(lines)


def format_shop(state: dict) -> str:
    lines = [format_state(state)]
    shop = state['shop']
    idx = 0
    lines.append(f"\nShop inventory (you have {state['gold']} gold):")
    lines.append("Cards:")
    for c in shop['cards']:
        upgraded = "+" if c['upgraded'] else ""
        affordable = "" if c['price'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"  [{idx}] {c['name']}{upgraded} (cost {c['cost']}) [{c['type']}] - {c['price']}g{affordable} - {c['description']}")
        idx += 1
    lines.append("Relics:")
    for r in shop['relics']:
        affordable = "" if r['price'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"  [{idx}] {r['name']} - {r['price']}g{affordable} - {r['description']}")
        idx += 1
    lines.append("Potions:")
    for p in shop['potions']:
        affordable = "" if p['price'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"  [{idx}] {p['name']} - {p['price']}g{affordable}")
        idx += 1
    if shop.get('card_removal_cost') is not None:
        affordable = "" if shop['card_removal_cost'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"\nCard removal: {shop['card_removal_cost']}g{affordable}")
    return "\n".join(lines)


def format_map(map_data: dict) -> str:
    lines = [
        f"=== MAP ===",
        f"Act {map_data['act']} - Boss: {map_data['boss']}",
        f"Current node: {map_data['current_node']}",
    ]
    nodes = {n['id']: n for n in map_data['nodes']}
    current = map_data.get('current_node')
    if current and current in nodes:
        children = nodes[current]['children']
        lines.append("\nNext nodes:")
        for cid in children:
            if cid in nodes:
                n = nodes[cid]
                # Trace path ahead
                path = [n['type']]
                nxt = n
                for _ in range(5):
                    if not nxt['children']:
                        break
                    nxt = nodes.get(nxt['children'][0])
                    if nxt is None:
                        break
                    path.append(nxt['type'])
                lines.append(f"  ({n['col']},{n['row']}): {n['type']} -> {' -> '.join(path[1:])}")
    return "\n".join(lines)


def format_card_select(state: dict) -> str:
    lines = [format_state(state)]
    cs = state['card_select']
    lines.append(f"\nCard selection ({cs['screen_type']}):")
    lines.append("Choose a card, then confirm:")
    for i, c in enumerate(cs['cards']):
        upgraded = "+" if c['upgraded'] else ""
        lines.append(f"  [{i}] {c['name']}{upgraded} ({c['cost']}) [{c['type']}] - {c['description']}")
    return "\n".join(lines)


def format_hand_select(state: dict) -> str:
    hs = state['hand_select']
    trigger = hs['trigger_card']
    desc = hs['trigger_description']
    min_sel = hs['min_select']
    max_sel = hs['max_select']

    if min_sel == max_sel:
        count_str = str(min_sel)
    else:
        count_str = f"{min_sel}-{max_sel}"

    lines = [
        f"=== CARD SELECTION ===",
        f"{trigger}: {desc}",
        f"Select {count_str} card(s):",
    ]
    for i, c in enumerate(hs['cards']):
        upgraded = "+" if c['upgraded'] else ""
        lines.append(f"  [{i}] {c['name']}{upgraded} (cost {c['cost']}) [{c['type']}] - {c['description']}")
    return "\n".join(lines)


def format_treasure(state: dict) -> str:
    lines = [format_state(state)]
    t = state.get('treasure', {})
    if t.get('relic_name'):
        lines.append(f"\nTreasure: {t['relic_name']} - {t['relic_description']}")
    lines.append("\nProceed to continue.")
    return "\n".join(lines)
