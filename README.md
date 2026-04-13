# vakuu

A benchmarking tool that lets LLM-driven agents play real runs of Slay the Spire 2. The project has two components: a C# mod that exposes game state and actions via a local HTTP API, and a Python agent harness that connects LLMs to that API.

## Architecture

```
┌─────────────┐       HTTP/JSON        ┌──────────────────┐
│   Vakuu     │◄──────────────────────►│  STS2 + BepInEx  │
│  (Python)   │   localhost:58232      │  Mod (C#)        │
│             │                        │                  │
│  - Claude   │  GET  /game/state      │  - Hooks into    │
│  - GPT-4    │  GET  /game/combat     │    game engine   │
│  - Gemini   │  POST /game/action     │  - Reads state   │
│  - etc.     │  ...                   │  - Executes acts │
└─────────────┘                        └──────────────────┘
```

## Components

### `sts2-headless/` — Game Mod (C#)

A Slay the Spire 2 mod built with Godot.NET.Sdk and Harmony that embeds an HTTP server inside the game. The server exposes game state as JSON and accepts player actions, allowing external programs to pilot the game.

**State Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server health check |
| `GET` | `/game/state` | Core game state + screen-specific data (events, rewards, shop, etc.) |
| `GET` | `/game/combat` | Combat details — player, enemies, hand, energy, intents |
| `GET` | `/game/combat/piles` | Draw pile, discard pile, exhaust pile |
| `GET` | `/game/map` | Full map graph with node types and connections |
| `GET` | `/game/deck` | Full deck listing |

**Action Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/game/action/combat` | Combat actions: `play_card`, `end_turn`, `use_potion` |
| `POST` | `/game/action` | Non-combat: `choose_map_node`, `choose_event_option`, `claim_reward`, `proceed`, `choose_rest_option`, `choose_card_reward`, `skip_card_reward`, `shop_buy`, `shop_remove_card`, `select_card`, `confirm_selection` |

Combat actions are **synchronous** — the response waits until the game is ready for the next input (card resolved, enemy turn finished, etc.).

The `/game/state` endpoint detects the current screen and includes screen-specific data:

| Screen | Data |
|--------|------|
| `combat` | Use `/game/combat` for details |
| `map` | Use `/game/map` for details |
| `event` / `ancient` | Event name, body text, options with descriptions |
| `card_reward` | Card choices with stats |
| `rewards` | Reward items (gold, card, potion, relic) |
| `rest` | Rest site options (rest, smith, etc.) |
| `shop` | Cards, relics, potions with prices; card removal cost |
| `card_select` | Card grid for upgrade/transform/remove |
| `treasure` | Relic obtained |

### `sts2-agent/` — Agent Harness (Python)

The harness connects an LLM to the game API using tool_use for structured action execution.

**How it works:**
1. Polls `/game/state` to determine the current screen
2. Formats game state into a readable prompt
3. Sends to the LLM with screen-appropriate tools
4. LLM responds with a tool call (e.g. `play_card(card_name="Bash", target_index=0)`)
5. Harness resolves the call (e.g. card name → hand index) and executes via the API
6. Result sent back to LLM for follow-up actions
7. Conversation history clears on screen transitions to keep context lean

**Features:**
- Name-based card play (LLM says "play Bash" instead of guessing indices)
- Type-based reward claiming (`claim_reward(reward_type="gold")`)
- Utility tools: `view_deck`, `view_map`, `view_draw_pile`
- Automatic context clearing between screens with strategic summary seeding
- Postmortem analysis on death
- Anti-thrashing detection for stuck screens

## Setup

### Mod

1. Install Slay the Spire 2 via Steam
2. Install [MegaDot](https://github.com/nickhealthy/MegaDot) v4.5.1 for Godot .NET SDK
3. Build and deploy:
   ```
   cd sts2-headless
   dotnet build
   ```
   The build automatically copies the DLL to the game's mods folder.

### Agent

1. Install Python 3.11+
2. Install dependencies:
   ```
   cd sts2-agent
   pip install -r requirements.txt
   ```
3. Run:
   ```
   python main.py --model claude-sonnet-4-6 --api-key sk-ant-...
   ```
   Or set `ANTHROPIC_API_KEY` as an environment variable and omit `--api-key`.

### Running a Benchmark

1. Launch STS2 with mods enabled
2. Start a new run (select character, ascension level)
3. Run the agent — it takes over from the current screen
4. Watch the agent play in real time

## Status

**Working:**
- Full game state extraction for all screen types
- Combat actions (play cards, end turn, use potions) with sync wait
- Non-combat actions (map, events, rewards, rest, shop, card selection)
- Name-based card resolution (no index guessing)
- Claude provider with tool_use

**Known Issues / TODO:**
- Character-specific mechanics (Regent stars, Necrobinder Osty, Defect orbs)
- Some dynamic relic descriptions don't fully resolve
- Screen transitions can occasionally need a re-poll
- OpenAI / Gemini provider adapters not yet implemented
- Run logging and metrics collection
- Multi-run batch benchmarking
- Seed control for reproducible comparisons
