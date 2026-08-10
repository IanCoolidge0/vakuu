"""Enemy compendium — injected into combat prompts to give the agent
full context on each enemy's HP, moves, and attack pattern."""

import json
from pathlib import Path

# Ascension thresholds at which specific field overrides apply.
# For each field prefix, the list is ordered high → low so we pick the
# highest applicable prefix for the current ascension level.
_ASCENSION_PREFIXES = [19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]

_cache: dict | None = None


def _load() -> dict:
    """Load and merge every act's compendium from enemies/*.json.

    Returns {"enemies": {name: entry}, "summons": {summoner: [minions]}}.
    Enemy names are globally unique across acts, so merging is flat."""
    global _cache
    if _cache is None:
        merged_enemies: dict = {}
        merged_summons: dict = {}
        for path in sorted((Path(__file__).parent / "enemies").glob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged_enemies.update(data.get("enemies", {}))
            merged_summons.update(data.get("_meta", {}).get("summons", {}))
        _cache = {"enemies": merged_enemies, "summons": merged_summons}
    return _cache


def _pick(entry: dict, field: str, ascension: int):
    """Return `entry[a{N}_{field}]` for the highest N <= ascension that
    has a value, falling back to `entry[field]`."""
    for n in _ASCENSION_PREFIXES:
        if n <= ascension:
            key = f"a{n}_{field}"
            if key in entry:
                return entry[key]
    return entry.get(field)


def get_enemy_entry(name: str) -> dict | None:
    """Look up a compendium entry by enemy display name."""
    data = _load()
    return data.get("enemies", {}).get(name)


def format_enemy_block(name: str, ascension: int = 0) -> str | None:
    """Return a formatted multi-line block for a single enemy, or None if
    no compendium entry exists. Only the numbers relevant to the current
    ascension are shown."""
    entry = get_enemy_entry(name)
    if entry is None:
        return None

    lines = [f"{name} ({entry.get('tier', 'enemy')}):"]

    hp = _pick(entry, "hp", ascension)
    if hp:
        lines.append(f"  HP: {hp}")

    powers = _pick(entry, "powers", ascension) or []
    if powers:
        lines.append("  Powers: " + "; ".join(powers))

    moves = _pick(entry, "moves", ascension) or []
    if moves:
        lines.append("  Moves:")
        for m in moves:
            lines.append(f"    - {m}")

    pattern = _pick(entry, "pattern", ascension)
    if pattern:
        lines.append(f"  Pattern: {pattern}")

    return "\n".join(lines)


def format_keywords_section(character: str | None) -> str:
    """Terse keyword glossary for the system prompt: neutral keywords plus
    the section matching the current character. Returns '' if no data.
    Kept minimal — one line per keyword, mechanical definitions only."""
    path = Path(__file__).parent / "keywords.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    entries = dict(data.get("neutral", {}))
    if character:
        for key, kws in data.get("characters", {}).items():
            if key.lower() in character.lower():
                entries.update(kws)
    if not entries:
        return ""
    lines = [f"{k}: {v}" for k, v in entries.items()]
    return "## Keywords\n" + "\n".join(lines)


def format_enchantment_mentions(*texts: str | None) -> str:
    """One-line definitions for enchantment names appearing bare in the given
    texts (event bodies/options). Enchanted cards self-describe via their DTO;
    this covers mentions like 'Enchant all cards ... with Glam'. Returns ''
    when nothing matches."""
    import re
    path = Path(__file__).parent / "enchantments.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    blob = " ".join(t for t in texts if t)
    hits = []
    for name, definition in data.get("enchantments", {}).items():
        # Word-boundary match; 'Swift Potion' must not trigger 'Swift'.
        if re.search(rf"\b{re.escape(name)}\b(?! Potion)", blob):
            hits.append(f"  {name}: {definition}")
    if not hits:
        return ""
    return "Enchantments mentioned:\n" + "\n".join(hits)


def format_enemies_section(names: list[str], ascension: int = 0) -> str:
    """Format a section for all known enemies in the encounter. Silently
    omits enemies without entries. Returns empty string if no entries match."""

    # Append minion info for enemies that spawn minions, per each act's
    # _meta.summons mapping.
    summons = _load().get("summons", {})
    names = list(names)
    for name in list(names):
        names.extend(summons.get(name, []))

    blocks = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        block = format_enemy_block(name, ascension)
        if block is not None:
            blocks.append(block)
    if not blocks:
        return ""
    return "=== ENCOUNTER NOTES ===\n" + "\n\n".join(blocks)
