---
description: Spawn a background subagent to play the active Slay the Spire 2 run
---

Spawn a general-purpose background subagent (run_in_background=true) with the prompt below. Do not include any strategic hints (card priorities, combat heuristics, map routing tips). Do not run the agent in the foreground. After launching, end your turn — you'll be notified when it completes.

Subagent prompt:

---

You are playing a real run of Slay the Spire 2 by hitting an HTTP API directly. The mod's API server is running on `http://localhost:58232`. There is already an active run waiting for you. Your goal is to play well — clear acts, defeat bosses, win the run.

Use the Bash tool to issue `curl` commands. No other tools are needed (don't read game source code — the API summary below is sufficient, and reading code burns context you'd rather spend on play decisions).

## How to play

Each turn:
1. `curl http://localhost:58232/game/state` — returns JSON describing the current screen (combat, map, event, shop, rest, treasure, card_reward, rewards, card_select, hand_select, ancient).
2. Decide what to do based on the screen + state.
3. POST an action.
4. Repeat.

## API endpoints

**Reads (GET):**
- `/health` — basic ping
- `/game/state` — current screen + general state. Always start each turn here.
- `/game/combat` — full combat detail: hand, enemies (with intents), powers, energy, pile counts, potions, relics
- `/game/combat/piles` — draw / discard / exhaust pile contents
- `/game/map` — full act map
- `/game/deck` — your full deck

**Actions (POST `/game/action/combat`, body is JSON):**
- `{"type":"play_card","card_index":N}` — play hand card at index N. Add `"target_index":M` for single-target attacks.
- `{"type":"end_turn"}`
- `{"type":"use_potion","potion_index":N}` — add `"target_index"` if it targets an enemy
- `{"type":"select_hand_card","card_index":N}` — pick a card during in-combat hand-selection prompts (e.g. Armaments)

**Actions (POST `/game/action`, body is JSON). Most use `card_index` as a generic index field:**
- `{"type":"choose_map_node","col":C,"row":R}`
- `{"type":"choose_event_option","card_index":N}` (option index)
- `{"type":"claim_reward","card_index":N}` (reward index — 0 is usually fine; loop to claim each)
- `{"type":"proceed"}` — advance from rewards/event/shop/etc.
- `{"type":"choose_rest_option","card_index":N}`
- `{"type":"choose_card_reward","card_index":N}` — pick from card-reward overlay
- `{"type":"skip_card_reward"}`
- `{"type":"shop_buy","card_index":N}` — N is the cumulative slot index (cards first, then relics, then potions, in the order /game/state returns them)
- `{"type":"shop_remove_card"}` — pay to open card-removal selection
- `{"type":"select_card","card_index":N}` — pick a card on a card-grid screen (upgrade/transform/remove). Then `{"type":"confirm_selection"}` to confirm.
- `{"type":"confirm_selection"}` — confirm an action on a selected card after selected via `{"type":"select_card"}`. (upgrade/transform/remove). 
- `{"type":"open_chest"}`, `{"type":"pick_relic","card_index":N}`

The server settles transitions automatically — after a successful action, the next `/game/state` will reflect the post-animation state (hand fully drawn, etc).

## Curl tip

Use `-s` and pipe through `python -c "import sys,json; print(json.dumps(json.loads(sys.stdin.read()),indent=2))"` if you want pretty output, or just inspect raw. For POSTs:
```
curl -s -X POST http://localhost:58232/game/action/combat -H 'Content-Type: application/json' -d '{"type":"play_card","card_index":0,"target_index":0}'
```

## Reporting

While playing, give brief status notes after each major event (boss kills, deaths, big card additions). Don't narrate every play. When the run ends (death or victory), give a short postmortem summary.

Stop conditions:
- If `/game/state` returns `{"error":"No active run"}` — the run is over, report and exit.
- If you take 200+ actions without progress, summarize and exit.
- If you see the same screen 10+ turns in a row with no state change, you're stuck — try `proceed`, then summarize and exit.

Begin by hitting `/health` and `/game/state` to confirm the server is alive and see where you are.
