"""clean_desc: strips engine markup from card/relic text (icon resource
paths, half-stripped localization templates) and single-lines descriptions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handlers.formatters import clean_desc

E = "res://images/packed/sprite_fonts/ironclad_energy_icon.png"


def main():
    # Energy icon runs become one [E] per icon
    assert clean_desc(f"If you Exhausted a card this turn, gain {E}{E}{E}.") == \
        "If you Exhausted a card this turn, gain [E][E][E]."
    # Template remnants ')|}' are stripped
    assert clean_desc("Gain  for each Attack in your Hand.\nYou cannot gain\nadditional  this turn.)|}") == \
        "Gain  for each Attack in your Hand. You cannot gain additional  this turn.)"
    # Multi-line descriptions join to a single line (column-0 continuations
    # read as new list items in the line-oriented prompt format)
    assert clean_desc("Deal 8 damage.\nApply 2 Vulnerable.") == "Deal 8 damage. Apply 2 Vulnerable."
    # The double-space from missing mod-side values is preserved (visible bug
    # signal, deliberately not masked)
    assert clean_desc("Gain  Block.\nExhaust 1 card.") == "Gain  Block. Exhaust 1 card."
    # Event bodies keep their line breaks
    assert "\n" in clean_desc("Line one.\nLine two.", keep_newlines=True)
    assert clean_desc(None) == ""
    print("clean_desc OK")


if __name__ == "__main__":
    main()
