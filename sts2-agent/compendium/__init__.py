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
    global _cache
    if _cache is None:
        path = Path(__file__).parent / "enemies.json"
        with open(path, "r", encoding="utf-8") as f:
            _cache = json.load(f)
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


def format_enemies_section(names: list[str], ascension: int = 0) -> str:
    """Format a section for all known enemies in the encounter. Silently
    omits enemies without entries. Returns empty string if no entries match."""
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
