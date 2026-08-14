"""Format game state into readable text for the LLM."""

import json
import re

from compendium import format_enemies_section, format_enchantment_mentions

# Card/relic text arrives from the mod with raw engine markup: inline icon
# resource paths ("gain res://...energy_icon.pngres://...energy_icon.png")
# and half-stripped localization templates (")|}"). Make it readable.
_ENERGY_ICON_RE = re.compile(r"res://\S*?energy_icon\.png")
_STAR_ICON_RE = re.compile(r"res://\S*?star_icon\.png")
_ICON_RE = re.compile(r"res://\S+?\.(?:png|svg|webp|jpe?g)")
_MARKUP_RE = re.compile(r"[{}|]")


def clean_desc(text, keep_newlines: bool = False) -> str:
    """Sanitize a card/relic/option description for the LLM prompt.

    Descriptions are joined to a single line by default: the prompt format is
    line-oriented, and a wrapped description continuing at column 0 can be
    misread as a new list item. keep_newlines=True is for prose blocks
    (event bodies) where line breaks aren't ambiguous."""
    if not text:
        return ""
    text = _ENERGY_ICON_RE.sub("[E]", text)  # each icon = 1 energy
    text = _STAR_ICON_RE.sub("[S]", text)    # each icon = 1 star (Regent)
    text = _ICON_RE.sub("", text)            # any other inline icon
    text = _MARKUP_RE.sub("", text)          # template remnants like ')|}'
    if not keep_newlines:
        parts = (p.strip() for p in text.splitlines())
        text = " ".join(p for p in parts if p)
    return text.strip()


def fmt_cost(cost) -> str:
    """Render a card cost — -1 is an X-cost card (spends all remaining energy)."""
    return "X" if cost == -1 else str(cost)


def fmt_card_cost(c) -> str:
    """Full cost of a card: energy, plus Stars when the card has a star cost
    (Regent; not mutually exclusive): '1', 'X', '1+2S', '0+XS'."""
    cost = fmt_cost(c['cost'])
    sc = c.get('star_cost')
    if sc is None:
        return cost
    return f"{cost}+{'X' if sc == -1 else sc}S"


def card_tags(c) -> str:
    """Type bracket with keyword flags: '[attack]', '[status, Unplayable]'.
    Keywords come from the card's structured keyword set (they are not part
    of description text) and reflect enchantment grants/removals."""
    tags = [c['type']]
    tags.extend(c.get('keywords') or [])
    return "[" + ", ".join(tags) + "]"


def ench_label(c) -> str:
    """Enchantment label without brackets: 'Sharp 2', 'Glam(disabled)'.
    Empty for unenchanted cards."""
    e = c.get('enchantment')
    if not e:
        return ""
    label = e['name']
    if e.get('amount') is not None:
        label += f" {e['amount']}"
    if e.get('disabled'):
        label += "(disabled)"
    return label


def ench_bracket(c) -> str:
    """Bracket appended to the card NAME so enchanted copies are
    distinguishable and addressable: 'Strike[Sharp 2]'. '(disabled)' mirrors
    the greyed-out icon in the visual game (e.g. Glam's once-per-combat
    Replay already consumed)."""
    label = ench_label(c)
    return f"[{label}]" if label else ""


def card_display_name(c) -> str:
    """Full display name: base name + upgrade suffix + enchantment bracket.
    This is the name play_card accepts."""
    return f"{c['name']}{'+' if c.get('upgraded') else ''}{ench_bracket(c)}"


def ench_definitions_section(cards) -> str:
    """Definitions for the enchantments present among `cards`, one line per
    unique label, using the game's resolved text (amounts included). Empty
    when no card is enchanted."""
    seen = {}
    for c in cards:
        label = ench_label(c)
        if label and label not in seen:
            seen[label] = clean_desc((c.get('enchantment') or {}).get('description', ''))
    if not seen:
        return ""
    return "ENCHANTMENTS:\n" + "\n".join(f"  {k}: {v}" for k, v in seen.items())

def format_orb_slots(orbs, total_slots) -> str:
    """Formatter for orb slots. Adds empty slots if the number of orb slots
    exceeds the number of provided orbs."""
    empty_slots = total_slots - len(orbs)
    line = " ".join(["()" for _ in range(empty_slots)])
    for orb in orbs[::-1]:
        if orb["type"] == "lightning":
            line += f" (L {orb["param1"]}/{orb["param2"]})"
        elif orb["type"] == "frost":
            line += f" (F {orb["param1"]}/{orb["param2"]})"
        elif orb["type"] == "dark":
            line += f" (D {orb["param1"]}/{orb["param2"]})"
        elif orb["type"] == "glass":
            line += f" (G {orb["param1"]}/{orb["param2"]})"
        elif orb["type"] == "plasma":
            line += f" (P)"
        else:
            print(f"{RED}Format error: unknown orb type {orb["type"]}{RESET}")
    return f"Orbs: {line}"

def format_combat(state: dict, combat: dict) -> str:
    lines = []

    # On turn 1 only, inject encounter notes from the compendium so the
    # agent knows each enemy's HP, moves, and attack pattern. Subsequent
    # turns within the same combat reuse the context already in history.
    if combat.get('turn') == 1:
        enemy_names = [e['name'] for e in combat.get('enemies', []) if not e.get('is_dead')]
        ascension = state.get('ascension', 0) if state else 0
        notes = format_enemies_section(enemy_names, ascension)
        if notes:
            lines.append(notes)
            lines.append("")

    lines += [
        f"=== COMBAT (Turn {combat['turn']}) ===",
        f"Energy: {combat['energy']}/{combat['max_energy']}",
    ]
    # Stars (Regent): shown whenever they're in play — nonzero, or a card in
    # hand has a star cost (zero Stars is then load-bearing information).
    stars = combat.get('stars') or 0
    if stars or any(c.get('star_cost') is not None for c in combat['hand']):
        lines.append(f"Stars: {stars}")
    lines.append(
        f"HP: {combat['player']['hp']}/{combat['player']['max_hp']} | Block: {combat['player']['block']}")

    if combat['player']['powers']:
        powers = ", ".join(f"{p['name']}({p['amount']})" for p in combat['player']['powers'])
        lines.append(f"Your powers: {powers}")

    # Osty (Necrobinder): shown whenever the character is Necrobinder,
    # or if Osty is verified alive (e.g. due to a cross-character card.)
    # Flags a false negative if Osty is available but dead on a non-Necrobinder
    # character, but this is sufficiently rare to ignore.
    if combat['player']['name'] == "The Necrobinder" or combat['osty']['is_alive']:
        osty = combat['osty']
        if osty['is_alive']:
            lines.append(f"Osty: {osty['hp'] / osty['max_hp']} | Block: {osty['block']}")
        else:
            lines.append(f"Osty is dead.")

    # Orbs (Defect): shown whenever the number of Orb slots exceeds zero.
    if combat['orb_slots'] > 0:
        lines.append(format_orb_slots(combat['orbs'], combat['orb_slots']))

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
        lines.append(f"  [{i}] {card_display_name(c)} (cost {fmt_card_cost(c)}) {card_tags(c)} - {clean_desc(c['description'])}")

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

    ench_defs = ench_definitions_section(combat['hand'])
    if ench_defs:
        lines.append("")
        lines.append(ench_defs)

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
        lines.append(f"\n{clean_desc(event['body'], keep_newlines=True)}")
    lines.append("\nOptions:")
    for o in event['options']:
        locked = " [LOCKED]" if o['is_locked'] else ""
        lines.append(f"  [{o['index']}] {o['label']}{locked}: {clean_desc(o['description'])}")
    mentions = format_enchantment_mentions(
        event.get('body'), *(o.get('description') for o in event['options']))
    if mentions:
        lines.append("\n" + mentions)
    return "\n".join(lines)


def format_card_reward(state: dict) -> str:
    lines = [format_state(state)]
    lines.append("\nChoose a card to add to your deck (or skip):")
    for i, c in enumerate(state['card_reward']['cards']):
        lines.append(f"  [{i}] {card_display_name(c)} (cost {fmt_card_cost(c)}) {card_tags(c)} - {clean_desc(c['description'])}")
    ench_defs = ench_definitions_section(state['card_reward']['cards'])
    if ench_defs:
        lines.append("\n" + ench_defs)
    return "\n".join(lines)


def format_rewards(state: dict) -> str:
    lines = [format_state(state)]
    rewards = state['rewards']['rewards']
    if rewards:
        lines.append(f"\nRewards available ({len(rewards)}):")
        lines.append("Claim each reward, then proceed when done.")
        for i, r in enumerate(rewards):
            lines.append(f"  [{i}] {r['type']}: {clean_desc(r['description'])}")
    else:
        lines.append("\nAll rewards claimed. Proceed to continue.")
    return "\n".join(lines)


def format_rest(state: dict) -> str:
    lines = [format_state(state)]
    lines.append("\nRest site options:")
    for i, o in enumerate(state['rest_site']['options']):
        enabled = "" if o['is_enabled'] else " [DISABLED]"
        lines.append(f"  [{i}] {o['label']}{enabled}: {clean_desc(o['description'])}")
    return "\n".join(lines)


def format_shop(state: dict) -> str:
    lines = [format_state(state)]
    shop = state['shop']
    lines.append(f"\nShop inventory (you have {state['gold']} gold):")
    lines.append("Cards:")
    for c in shop['cards']:
        affordable = "" if c['price'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"  {card_display_name(c)} (cost {fmt_card_cost(c)}) {card_tags(c)} - {c['price']}g{affordable} - {clean_desc(c['description'])}")
    lines.append("Relics:")
    for r in shop['relics']:
        affordable = "" if r['price'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"  {r['name']} - {r['price']}g{affordable} - {clean_desc(r['description'])}")
    lines.append("Potions:")
    for p in shop['potions']:
        affordable = "" if p['price'] <= state['gold'] else " [CAN'T AFFORD]"
        lines.append(f"  {p['name']} - {p['price']}g{affordable}")
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
        lines.append(f"  [{i}] {card_display_name(c)} ({fmt_card_cost(c)}) {card_tags(c)} - {clean_desc(c['description'])}")
    ench_defs = ench_definitions_section(cs['cards'])
    if ench_defs:
        lines.append("\n" + ench_defs)
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
        f"{trigger}: {clean_desc(desc)}",
        f"Select {count_str} card(s):",
    ]
    for i, c in enumerate(hs['cards']):
        lines.append(f"  [{i}] {card_display_name(c)} (cost {fmt_card_cost(c)}) {card_tags(c)} - {clean_desc(c['description'])}")
    ench_defs = ench_definitions_section(hs['cards'])
    if ench_defs:
        lines.append("\n" + ench_defs)
    return "\n".join(lines)


def format_treasure(state: dict) -> str:
    lines = [format_state(state)]
    t = state.get('treasure', {})
    chest = t.get('chest_state', 'closed')
    relics = t.get('relics', []) or []

    if chest == 'closed':
        lines.append("\nThere is a closed chest in front of you. Use open_chest to reveal the relic.")
    elif chest == 'open':
        lines.append("\nThe chest is open. Pick a relic with pick_relic:")
        for i, r in enumerate(relics):
            lines.append(f"  [{i}] {r['name']} — {clean_desc(r.get('description', ''))}")
    elif chest == 'claimed':
        if relics:
            r = relics[0]
            lines.append(f"\nYou took: {r['name']} — {clean_desc(r.get('description', ''))}")
        lines.append("\nProceed to leave the treasure room.")
    return "\n".join(lines)
