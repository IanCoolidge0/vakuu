---
description: Spawn a background subagent to play the active Slay the Spire 2 run
---

Spawn a general-purpose background subagent (run_in_background=true) with the prompt below. Do not include any strategic hints (card priorities, combat heuristics, map routing tips). Do not run the agent in the foreground. After launching, end your turn — you'll be notified when it completes.

Subagent prompt:

---

You are playing a real run of Slay the Spire 2 by hitting an HTTP API directly. The mod's API server is running on `http://localhost:58232`. There is already an active run waiting for you. Your goal is to play well — clear acts, defeat bosses, win the run.

Use the Bash tool to issue `curl` commands. No other tools are needed (don't read game source code — the API summary below is sufficient, and reading code burns context you'd rather spend on play decisions). You may look at the files under `sts2-agent/compendium/` (per-act enemy files in `enemies/`, plus `keywords.json` and `enchantments.json`) to learn about specific encounters, keywords, etc. that are unfamiliar, but you are not allowed to read any other files.

## How to play

Each turn:
1. `curl http://localhost:58232/game/state` — returns JSON describing the current screen (combat, map, event, shop, rest, treasure, card_reward, rewards, card_select, hand_select, ancient, crystal_sphere, game_over).
2. Decide what to do based on the screen + state.
3. POST an action.
4. Repeat.

## API endpoints

**Reads (GET):**
- `/health` — basic ping
- `/game/state` — current screen + general state. Always start each turn here.
- `/game/combat` — full combat detail: hand, enemies (with intents), powers (each with a description of its effect), energy, pile counts, potions, relics
- `/game/combat/piles` — draw / discard / exhaust pile contents
- `/game/map` — full act map
- `/game/deck` — your full deck

**Actions (POST `/game/action/combat`, body is JSON):**
- `{"type":"play_card","card_index":N}` — play hand card at index N. Add `"target_index":M` for single-target attacks. Indices refer to the hand as it is when the request arrives: every play removes a card and can add others, so the cards after it shift.
- `{"type":"end_turn"}`
- `{"type":"use_potion","potion_index":N}` — add `"target_index"` if it targets an enemy. Outside combat it works only on a `shop` screen and only for a Foul Potion, which is thrown at the merchant (no target needed).
- `{"type":"select_hand_card","card_index":N}` — pick a card during in-combat hand-selection prompts (e.g. Armaments)

**Actions (POST `/game/action`, body is JSON). Most use `card_index` as a generic index field:**
- `{"type":"choose_map_node","col":C,"row":R}`
- `{"type":"choose_event_option","card_index":N}` (option index). Options with `"will_kill": true` kill you. An option that abandons the run is refused unless you add `"confirm": true`, matching the game's own confirmation popup.
- `{"type":"claim_reward","card_index":N}` (reward index — 0 is usually fine; loop to claim each)
- `{"type":"skip_rewards"}` — leave the rewards screen, forfeiting anything unclaimed (`proceed` refuses while rewards remain)
- `{"type":"proceed"}` — advance from rewards/event/shop/etc.
- `{"type":"choose_rest_option","card_index":N}`
- `{"type":"choose_card_reward","card_index":N}` — pick from card-reward overlay
- `{"type":"skip_card_reward"}`
- `{"type":"shop_buy","name":"<item name>"}` — buy a card, relic or potion by its name as listed in the shop (add `+` for an upgraded card, e.g. `"Strike+"`). Some events show up as a `shop` screen too; `proceed` leaves them.
- `{"type":"shop_remove_card"}` — pay to open card-removal selection
- `{"type":"select_card","card_index":N}` — pick a card on a card-grid screen (upgrade/transform/remove). Then `{"type":"confirm_selection"}` to confirm.
- `{"type":"confirm_selection"}` — confirm an action on a selected card after selected via `{"type":"select_card"}`. (upgrade/transform/remove). 
- `{"type":"open_chest"}`, `{"type":"pick_relic","card_index":N}`
- `{"type":"crystal_sphere_divine","tool":"big"|"small","x":X,"y":Y}` — the Crystal Sphere event's Divination minigame (`crystal_sphere` screen). Spends one divination: `big` uncovers the 3×3 area centred on cell (x, y), `small` just that cell. The state's `crystal_sphere.grid` is one string per row (y = 0 first, character x = column): `#` hidden, `.` uncovered and empty, otherwise the letter of the item in that cell. Each item has its own letter (`A`, `B`, …), assigned as items come into view. `crystal_sphere.items` maps each letter to the item's type (relic, card reward, potion, gold, curse). An item is won only once all of its cells are uncovered. Every board holds a 4×4 relic, three 2×2 card rewards (common/uncommon/rare), two 1×3 common potions, a 2×2 rare potion, two 2×1 big golds (30), five 1×1 small golds (10), and a 2×2 curse (adds Doubt to your deck). Sizes are width×height. After the last divination, claim the rewards, then `proceed`.

The server settles transitions automatically — after a successful action, the next `/game/state` will reflect the post-animation state (hand fully drawn, map travel finished, the event's next options shown, etc).

## Curl tip

Use `-s` and pipe through `python -c "import sys,json; print(json.dumps(json.loads(sys.stdin.read()),indent=2))"` if you want pretty output, or just inspect raw. For POSTs:
```
curl -s -X POST http://localhost:58232/game/action/combat -H 'Content-Type: application/json' -d '{"type":"play_card","card_index":0,"target_index":0}'
```

## Reporting

While playing, give brief status notes after each major event (boss kills, deaths, big card additions). Don't narrate every play. When the run ends (death or victory), give a short postmortem summary.

Stop conditions:
- If `/game/state` reports `"screen":"game_over"` — the run is over. `game_over.victory` says whether you won (HP reads 0 either way). Report and exit.
- If `/game/state` returns `{"error":"No active run"}` — the run is over, report and exit.
- If you take 200+ actions without progress, summarize and exit.
- If you see the same screen 10+ turns in a row with no state change, you're stuck — try `proceed`, then summarize and exit.

Begin by hitting `/health` and `/game/state` to confirm the server is alive and see where you are.
