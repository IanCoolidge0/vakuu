"""Persistent cross-run note store. Output side only — nothing reads these
back into prompts yet."""

import datetime
import os
import time
from pathlib import Path

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """Generate a ULID: 48-bit ms timestamp + 80 random bits, Crockford
    base32. Lexicographic order is creation order (ms resolution)."""
    val = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[val & 31])
        val >>= 5
    return "".join(reversed(chars))


class NoteStore:
    """Writes ULID-named markdown notes to a memory directory."""

    def __init__(self, memory_dir: str | Path = "memory"):
        self.dir = Path(memory_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def add(self, note: str, category: str, context: dict | None = None) -> str:
        """Write a note file and return its ULID. `context` entries (character,
        act, floor, ...) land in the frontmatter; None values are dropped."""
        note_id = ulid()
        lines = [
            "---",
            f"ulid: {note_id}",
            f"time: {datetime.datetime.now().isoformat(timespec='seconds')}",
            f"category: {category}",
        ]
        for k, v in (context or {}).items():
            if v is not None:
                lines.append(f"{k}: {v}")
        lines += ["---", "", note.strip(), ""]
        path = self.dir / f"{note_id}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return note_id
