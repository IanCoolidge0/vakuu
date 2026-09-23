"""Crystal Sphere (Divination) minigame: board formatting, tool routing and
the settle fingerprint that keeps the thrash detector from firing across
divinations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Agent
from handlers.formatters import format_crystal_sphere
from tools import get_tools_for_screen


def board(divinations, grid, items=None, can_proceed=False):
    return {
        "screen": "crystal_sphere", "character": "The Silent", "ascension": 0,
        "act": 2, "floor": 6, "hp": 50, "max_hp": 70, "gold": 40,
        "relics": [], "potions": [{"name": None}],
        "crystal_sphere": {"width": 11, "height": 11, "divinations_left": divinations,
                           "can_proceed": can_proceed, "grid": grid, "items": items or {}},
    }


FOG = ["#" * 11 for _ in range(11)]


def main():
    # Corners start uncovered; part of a relic and two touching golds showing
    grid = list(FOG)
    grid[0] = ".." + "#" * 7 + ".."
    grid[5] = "####AA#####"
    grid[6] = "####AABC###"
    items = {"A": "relic", "B": "gold", "C": "gold"}
    out = format_crystal_sphere(board(2, grid, items))

    assert "Divinations left: 2" in out
    # Column header and row labels line up with the 3-wide cells
    assert "   x  0  1  2  3  4  5  6  7  8  9 10" in out, out
    assert "y  6  #  #  #  #  A  A  B  C  #  #  #" in out, out
    # Each item keeps its own letter; the legend maps letters to types
    assert "Items showing: A relic, B gold, C gold" in out, out
    # Cells only: no item footprints
    assert "cells uncovered" not in out and " at x " not in out, out
    # Fixed contents are listed with sizes
    assert "1 relic 4x4" in out and "5 gold (small, 10) 1x1" in out, out
    assert "Use crystal_sphere_divine" in out
    print("board OK")

    done = format_crystal_sphere(board(0, grid, can_proceed=True))
    assert "Proceed to leave." in done
    print("finished OK")

    names = [t["name"] for t in get_tools_for_screen("crystal_sphere")]
    assert "crystal_sphere_divine" in names and "proceed" in names, names
    print("tools OK")

    # Each divination changes the board: the fingerprint must see it, or
    # the same-screen thrash detector stalls a 6-divination Payment Plan run
    fp = Agent._state_fingerprint
    before = board(3, FOG)
    after_grid = list(FOG)
    after_grid[5] = "####...####"
    after = board(2, after_grid)
    assert fp(before) != fp(after), "divination not observed"
    assert fp(before) == fp(board(3, FOG)), "identical board produced diff"
    print("fingerprint OK")


if __name__ == "__main__":
    main()
