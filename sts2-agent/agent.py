"""Main agent loop — polls game state, prompts LLM, executes actions."""

import builtins
import json
import time
import traceback

# Override print to always flush
_original_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _original_print(*args, **kwargs)

from client import GameClient
from llm.base import LLMProvider
from tools import get_tools_for_screen
from handlers.formatters import (
    format_combat, format_state, format_event, format_card_reward,
    format_rewards, format_rest, format_shop, format_map, format_treasure,
    format_card_select, format_hand_select, fmt_cost,
)

# ANSI color codes
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


class Agent:
    def __init__(self, llm: LLMProvider, client: GameClient, verbose: bool = True,
                 logger=None):
        self.llm = llm
        self.client = client
        self.verbose = verbose
        self.logger = logger
        self.last_act = 0
        self.action_count = 0
        self.max_actions = 2000  # safety limit per run
        self._last_screen = None
        self._same_screen_count = 0
        self._pending_tool_calls = False

    def run(self):
        """Main loop — play until the run ends or we hit the action limit."""
        print(f"{BOLD}Agent starting. Waiting for game connection...{RESET}")
        self.client.health()
        print(f"{GREEN}Connected to STS2.{RESET}")

        while self.action_count < self.max_actions:
            # Check if game is still running
            try:
                self.client.health()
            except Exception:
                print(f"\n{RED}Game disconnected.{RESET}")
                print(f"Total actions: {self.action_count}")
                return

            try:
                state = self.client.get_state()
            except Exception as e:
                print(f"{RED}Failed to get state: {e}. Retrying...{RESET}")
                time.sleep(1)
                continue

            if "error" in state:
                error = state['error']
                if error == "No active run":
                    print(f"\n{BOLD}{RED}{'='*60}")
                    print(f"  RUN ENDED")
                    print(f"{'='*60}{RESET}")
                    print(f"Total actions: {self.action_count}")
                    return
                print(f"{RED}Game error: {error}. Waiting...{RESET}")
                time.sleep(2)
                continue

            # Check for death
            if state.get("hp", 1) <= 0:
                print(f"\n{BOLD}{RED}")
                print(f"  ╔═══════════════════════════════════════╗")
                print(f"  ║           VAKUU HAS FALLEN            ║")
                print(f"  ║         Floor {str(state.get('floor', '?')).center(24)}║")
                print(f"  ╚═══════════════════════════════════════╝{RESET}")
                print(f"  Total actions: {self.action_count}")
                self._postmortem(state)
                return

            screen = state.get("screen", "unknown")

            # Clear history on major screen transitions — keep context lean
            # Never clear if we have pending tool calls (would corrupt message history)
            # Don't clear on closely related screen flows
            related_screens = {
                ("rewards", "card_reward"),
                ("rewards", "card_select"),
                ("card_reward", "card_select"),
                ("combat", "hand_select"),
                ("rest", "card_select"),
                ("shop", "card_select"),
                ("event", "card_select"),
                ("ancient", "card_select")
            }
            is_related = (self._last_screen, screen) in related_screens or (screen, self._last_screen) in related_screens
            if screen != self._last_screen and not is_related and not self._pending_tool_calls:
                self.llm.clear_history()
                # Seed with strategic summary so the model has context
                summary = self._build_summary(state)
                if summary:
                    self.llm.messages.append({"role": "user", "content": summary})
                    self.llm.messages.append({"role": "assistant", "content": "Understood. I'll make decisions based on this game state."})

            act = state.get("act", 0)
            if act != self.last_act and self.last_act > 0:
                print(f"\n{BOLD}{MAGENTA}{'='*60}")
                print(f"  ACT {act}")
                print(f"{'='*60}{RESET}\n")
            self.last_act = act

            # Transition states — wait for game to settle
            if screen in ("waiting", "unknown"):
                if self.verbose:
                    print(f"{DIM}  ({screen} — waiting for transition...){RESET}")
                time.sleep(0.5)
                continue

            # Detect thrashing — same screen too many times (exempt combat, it's naturally long)
            if screen == self._last_screen and screen != "combat":
                self._same_screen_count += 1
                if self._same_screen_count > 5:
                    print(f"{YELLOW}Stuck on '{screen}' for {self._same_screen_count} iterations, waiting...{RESET}")
                    time.sleep(2)
                    if self._same_screen_count > 10:
                        print(f"{RED}Stuck too long, trying proceed...{RESET}")
                        try:
                            self.client.proceed()
                        except Exception:
                            pass
                        self._same_screen_count = 0
                    continue
            else:
                self._same_screen_count = 0
            self._last_screen = screen

            # Build the prompt and get tools for this screen
            prompt = self._build_prompt(screen, state)
            tools = get_tools_for_screen(screen)

            if self.verbose:
                hp = state.get('hp', '?')
                max_hp = state.get('max_hp', '?')
                gold = state.get('gold', '?')
                floor = state.get('floor', '?')
                hp_color = GREEN if hp > max_hp * 0.5 else (YELLOW if hp > max_hp * 0.25 else RED) if isinstance(hp, int) and isinstance(max_hp, int) else ""
                print(f"\n{BOLD}{CYAN}{'─'*60}")
                print(f"  {screen.upper()} | Floor {floor} | {hp_color}HP {hp}/{max_hp}{CYAN} | Gold {gold} | Action #{self.action_count}")
                print(f"{'─'*60}{RESET}")
            if self.logger:
                self.logger.screen(screen, self.action_count,
                                   f"{state.get('hp', '?')}/{state.get('max_hp', '?')}",
                                   state.get('gold', '?'), state.get('floor', '?'))

            if not tools:
                print(f"{YELLOW}No tools for screen '{screen}', trying to proceed...{RESET}")
                try:
                    self.client.proceed()
                except Exception:
                    pass
                time.sleep(1)
                continue

            # Send to LLM and execute tool calls
            self._take_action(prompt, tools, screen, state)

        print(f"\n{YELLOW}Action limit reached ({self.max_actions}).{RESET}")
        print(f"Total actions: {self.action_count}")

    def _postmortem(self, final_state: dict):
        """Ask the LLM for a short postmortem analysis of the run."""
        summary = self._build_summary(final_state)

        try:
            deck = self.client.get_deck()
            deck_str = "\n".join(
                f"  {c['name']}{'+ ' if c['upgraded'] else ''} ({fmt_cost(c['cost'])}) [{c['type']}]"
                for c in deck.get("cards", [])
            )
        except Exception:
            deck_str = "(unavailable)"

        prompt = f"""{summary}

Final deck:
{deck_str}

You died. Write a brief postmortem (3-5 sentences) analyzing:
- What went well this run
- What went wrong
- What you would do differently next time"""

        self.llm.clear_history()
        try:
            text, _ = self.llm.send(prompt, [])
            if text:
                print(f"\n{BOLD}{CYAN}--- VAKUU'S POSTMORTEM ---{RESET}")
                print(f"{MAGENTA}{text}{RESET}")
        except Exception as e:
            print(f"{RED}Postmortem failed: {e}{RESET}")

    def _resolve_reward_index(self, reward_type: str) -> int | None:
        """Resolve a reward type to its index on the rewards screen."""
        try:
            state = self.client.get_state()
            rewards = state.get("rewards", {}).get("rewards", [])
            for i, r in enumerate(rewards):
                if r["type"] == reward_type:
                    return i
        except Exception:
            pass
        return None

    def _resolve_card_index(self, card_name: str) -> int | None:
        """Resolve a card name to its index in the current hand."""
        try:
            combat = self.client.get_combat()
            hand = combat.get("hand", [])
            # Strip trailing "+" that the formatter adds for upgraded cards
            base_name = card_name.rstrip("+").rstrip()
            # Exact match first (with upgrade suffix)
            for i, card in enumerate(hand):
                display = card["name"] + ("+" if card["upgraded"] else "")
                if display.lower() == card_name.lower().replace(" +", "+"):
                    return i
            # Match by base name
            for i, card in enumerate(hand):
                if card["name"].lower() == base_name.lower():
                    return i
            # Partial match fallback
            for i, card in enumerate(hand):
                if base_name.lower() in card["name"].lower():
                    return i
        except Exception:
            pass
        return None

    def _resolve_hand_select_index(self, card_name: str) -> int | None:
        """Resolve a card name to its index in the pending hand selection options."""
        try:
            state = self.client.get_state()
            cards = state.get("hand_select", {}).get("cards", [])
            # Exact match first
            for i, card in enumerate(cards):
                if card["name"].lower() == card_name.lower():
                    return i
            # Partial match fallback
            for i, card in enumerate(cards):
                if card_name.lower() in card["name"].lower():
                    return i
        except Exception:
            pass
        return None

    def _build_summary(self, state: dict) -> str:
        """Build a strategic context summary for the start of a new screen."""
        lines = [
            "=== RUN STATUS ===",
            f"{state.get('character', '?')} | Ascension {state.get('ascension', 0)} | Act {state.get('act', '?')} Floor {state.get('floor', '?')}",
            f"HP: {state.get('hp', '?')}/{state.get('max_hp', '?')} | Gold: {state.get('gold', '?')}",
        ]

        relics = state.get("relics", [])
        if relics:
            relic_strs = []
            for r in relics:
                s = r['name']
                if r.get('counter') is not None:
                    s += f" [{r['counter']}]"
                if r.get('description'):
                    s += f" ({r['description']})"
                relic_strs.append(s)
            lines.append("Relics: " + ", ".join(relic_strs))

        potions = state.get("potions", [])
        potion_strs = [p['name'] or '(empty)' for p in potions]
        lines.append("Potions: " + ", ".join(potion_strs))

        # Include deck
        try:
            deck = self.client.get_deck()
            cards = deck.get("cards", [])
            if cards:
                lines.append(f"\nDeck ({len(cards)} cards):")
                for c in cards:
                    up = "+" if c['upgraded'] else ""
                    lines.append(f"  {c['name']}{up} ({fmt_cost(c['cost'])}) [{c['type']}] - {c['description']}")
        except Exception:
            pass

        return "\n".join(lines)

    def _build_prompt(self, screen: str, state: dict) -> str:
        match screen:
            case "combat":
                try:
                    combat = self.client.get_combat()
                    # Wait for hand to be drawn if not full (combat just started)
                    retries = 0
                    while len(combat.get("hand", [])) < 4 and retries < 20:
                        time.sleep(0.5)
                        combat = self.client.get_combat()
                        retries += 1
                    return format_combat(state, combat)
                except Exception:
                    return format_state(state) + "\n(Failed to get combat details)"
            case "hand_select":
                return format_hand_select(state)
            case "event" | "ancient":
                return format_event(state)
            case "card_reward":
                return format_card_reward(state)
            case "rewards":
                return format_rewards(state)
            case "rest":
                return format_rest(state)
            case "shop":
                return format_shop(state)
            case "treasure":
                return format_treasure(state)
            case "card_select":
                return format_card_select(state)
            case "map":
                try:
                    map_data = self.client.get_map()
                    return format_state(state) + "\n\n" + format_map(map_data)
                except Exception:
                    return format_state(state) + "\n(Failed to get map)"
            case _:
                return format_state(state) + f"\nUnknown screen type: {screen}. Try to proceed."

    def _take_action(self, prompt: str, tools: list[dict], screen: str, state: dict):
        """Send prompt to LLM, handle tool calls in a loop."""
        if self.logger:
            self.logger.prompt(prompt)
        try:
            text, tool_calls = self.llm.send(prompt, tools)
        except Exception as e:
            print(f"{RED}LLM error: {e}{RESET}")
            print(f"{YELLOW}Clearing conversation history to recover...{RESET}")
            if self.logger:
                self.logger.error(f"LLM error (send): {e}")
            self.llm.clear_history()
            return

        if text:
            print(f"{MAGENTA}{text}{RESET}")
        if self.logger:
            self.logger.llm_text(text)
            self.logger.usage(getattr(self.llm, "last_usage", None))

        # Handle tool call loop
        max_tool_rounds = 5
        self._pending_tool_calls = False
        for _ in range(max_tool_rounds):
            if not tool_calls:
                self._pending_tool_calls = False
                break

            self._pending_tool_calls = True

            # Execute all tool calls and collect results
            results = []
            screen_changed = False
            new_screen_state: dict | None = None  # set if screen changed
            for tool_call in tool_calls:
                name = tool_call['name']
                inp = tool_call['input']
                inp_str = ", ".join(f"{k}={v}" for k, v in inp.items()) if inp else ""

                print(f"  {BOLD}{GREEN}>>> {name}({inp_str}){RESET}")
                if self.logger:
                    self.logger.tool_call(name, inp)

                try:
                    result = self._execute_tool(tool_call, screen, state)
                    self.action_count += 1
                except Exception as e:
                    result = json.dumps({"error": str(e)})

                if self.logger:
                    self.logger.tool_result(name, result)

                # Check if a combat action triggered a screen change:
                #  - play_card → hand_select (Armaments etc.) or rewards (kill)
                #  - end_turn → rewards (poison/DoT kills enemy on turn-end)
                #  - use_potion → rewards (damage potion kills) or hand_select
                #  - select_hand_card → combat or onward if that selection ended combat
                # Without this, the LLM keeps acting on the old screen's tools
                # (e.g. proceeds past unclaimed rewards after an end_turn kill).
                _screen_changing = {"play_card", "end_turn", "use_potion", "select_hand_card"}
                if name in _screen_changing and not screen_changed:
                    try:
                        result_data = json.loads(result)
                        if isinstance(result_data, dict) and result_data.get("success"):
                            check = self.client.get_state()
                            if check.get("screen") != screen:
                                screen_changed = True
                                new_screen_state = check
                    except Exception:
                        pass

                # Check for errors to show
                try:
                    result_data = json.loads(result)
                    if isinstance(result_data, dict) and result_data.get("error"):
                        print(f"  {RED}!!! {result_data['error']}{RESET}")
                except (json.JSONDecodeError, TypeError):
                    pass

                results.append({"tool_use_id": tool_call['id'], "content": result})

            # If a combat action changed the screen (e.g. play Survivor →
            # hand_select), piggy-back the new screen's prompt + tools onto
            # the tool_result in the same round-trip. This lets the LLM plan
            # once with full context instead of pre-emptively guessing on
            # the old screen and re-deciding on the next turn.
            extra_text = None
            next_tools = tools
            if screen_changed and new_screen_state is not None:
                new_screen = new_screen_state.get("screen")
                next_tools = get_tools_for_screen(new_screen)
                try:
                    new_prompt = self._build_prompt(new_screen, new_screen_state)
                    extra_text = (
                        f"The game transitioned to a new screen ({new_screen}). "
                        f"Act on the new screen using its tools:\n\n{new_prompt}"
                    )
                except Exception:
                    extra_text = None

            # Always send all results back - never leave dangling tool_use blocks
            try:
                text, tool_calls = self.llm.send_tool_results(
                    results, next_tools, extra_text=extra_text
                )
                self._pending_tool_calls = bool(tool_calls)
            except Exception as e:
                print(f"{RED}LLM error on tool result: {e}{RESET}")
                # Conversation is now broken — clear history to recover
                print(f"{YELLOW}Clearing conversation history to recover...{RESET}")
                if self.logger:
                    self.logger.error(f"LLM error (send_tool_results): {e}")
                self.llm.clear_history()
                self._pending_tool_calls = False
                break

            if text:
                print(f"{MAGENTA}{text}{RESET}")
            if self.logger:
                self.logger.llm_text(text)
                self.logger.usage(getattr(self.llm, "last_usage", None))

            # After a screen change, update the loop's view of the current
            # screen/tools so any further iterations operate on the new
            # screen. Reset screen_changed so additional transitions inside
            # this loop are detected correctly.
            if screen_changed and new_screen_state is not None:
                screen = new_screen_state.get("screen")
                tools = next_tools
                state = new_screen_state
                screen_changed = False
                new_screen_state = None

        # If the loop exited with pending tool_use blocks (max rounds,
        # screen change, etc.), send cancellation results to close them
        # properly instead of nuking the entire conversation history.
        # Critically, pass tools=[] so the model's response is guaranteed
        # text-only — otherwise it may emit another tool_use in reply to
        # the cancellation, leaving a new dangling tool_use that will
        # brick the next turn and force a catastrophic history clear.
        if tool_calls:
            dummy_results = [
                {"tool_use_id": tc['id'],
                 "content": json.dumps({"error": "Action cancelled — screen changed."})}
                for tc in tool_calls
            ]
            try:
                _, leftover = self.llm.send_tool_results(dummy_results, [])
                if leftover:
                    # Shouldn't happen with tools=[] but defend against it.
                    self.llm.clear_history()
            except Exception:
                self.llm.clear_history()
            self._pending_tool_calls = False

    def _execute_tool(self, tool_call: dict, screen: str, state: dict) -> str:
        """Execute a tool call and return the result as a string."""
        name = tool_call["name"]
        inp = tool_call["input"]

        try:
            match name:
                # Combat actions
                case "play_card":
                    card_index = inp.get("card_index")
                    card_name = inp.get("card_name")
                    if card_name and card_index is None:
                        # Resolve name to index from current hand
                        card_index = self._resolve_card_index(card_name)
                        if card_index is None:
                            return json.dumps({"error": f"Card '{card_name}' not found in hand."})
                    if card_index is None:
                        return json.dumps({"error": "play_card requires card_name or card_index."})
                    result = self.client.play_card(
                        card_index,
                        inp.get("target_index"),
                    )
                case "end_turn":
                    result = self.client.end_turn()
                case "use_potion":
                    result = self.client.use_potion(
                        inp["potion_index"],
                        inp.get("target_index"),
                    )

                # Map
                case "choose_map_node":
                    result = self.client.choose_map_node(inp["col"], inp["row"])

                # Events
                case "choose_event_option":
                    result = self.client.choose_event_option(inp["option_index"])

                # Card rewards
                case "choose_card_reward":
                    result = self.client.choose_card_reward(inp["card_index"])
                case "skip_card_reward":
                    result = self.client.skip_card_reward()

                # Rewards
                case "claim_reward":
                    reward_type = inp.get("reward_type")
                    reward_index = inp.get("reward_index", inp.get("card_index"))
                    if reward_type and reward_index is None:
                        # Resolve type to index from current rewards
                        reward_index = self._resolve_reward_index(reward_type)
                        if reward_index is None:
                            return json.dumps({"error": f"No '{reward_type}' reward available."})
                    if reward_index is None:
                        reward_index = 0
                    result = self.client.claim_reward(reward_index)
                case "proceed":
                    result = self.client.proceed()

                # Rest site
                case "choose_rest_option":
                    result = self.client.choose_rest_option(inp["option_index"])

                # Shop
                case "shop_buy":
                    result = self.client.shop_buy(inp.get("slot_index", inp.get("card_index", 0)))
                case "shop_remove_card":
                    result = self.client.shop_remove_card()

                # In-combat hand card selection (e.g. Armaments, Acrobatics)
                case "select_hand_card":
                    card_name = inp.get("card_name")
                    if not card_name:
                        return json.dumps({"error": "select_hand_card requires card_name."})
                    card_index = self._resolve_hand_select_index(card_name)
                    if card_index is None:
                        return json.dumps({"error": f"Card '{card_name}' not in selection options."})
                    result = self.client.select_hand_card(card_index)

                # Treasure room
                case "open_chest":
                    result = self.client.open_chest()
                case "pick_relic":
                    result = self.client.pick_relic(inp.get("index", 0))

                # Card selection (upgrade, transform, remove)
                case "select_card":
                    result = self.client._post("/game/action",
                        {"type": "select_card", "card_index": inp["card_index"]})
                case "confirm_selection":
                    result = self.client._post("/game/action",
                        {"type": "confirm_selection"})

                # Utility (read-only)
                case "view_deck":
                    deck = self.client.get_deck()
                    cards = deck.get("cards", [])
                    lines = [f"Deck ({len(cards)} cards):"]
                    for i, c in enumerate(cards):
                        up = "+" if c['upgraded'] else ""
                        lines.append(f"  [{i}] {c['name']}{up} ({fmt_cost(c['cost'])}) [{c['type']}]")
                    return "\n".join(lines)
                case "view_map":
                    map_data = self.client.get_map()
                    return format_map(map_data)
                case "view_draw_pile":
                    piles = self.client.get_combat_piles()
                    lines = [f"Draw pile ({piles['draw_pile_count']}):"]
                    for c in piles['draw_pile']:
                        lines.append(f"  {c['name']} ({fmt_cost(c['cost'])}) [{c['type']}]")
                    lines.append(f"\nDiscard pile ({len(piles['discard_pile'])}):")
                    for c in piles['discard_pile']:
                        lines.append(f"  {c['name']} ({fmt_cost(c['cost'])}) [{c['type']}]")
                    if piles['exhaust_pile']:
                        lines.append(f"\nExhaust pile ({len(piles['exhaust_pile'])}):")
                        for c in piles['exhaust_pile']:
                            lines.append(f"  {c['name']} ({fmt_cost(c['cost'])}) [{c['type']}]")
                    return "\n".join(lines)

                case _:
                    return json.dumps({"error": f"Unknown tool: {name}"})

            return json.dumps(result)

        except Exception as e:
            return json.dumps({"error": str(e), "traceback": traceback.format_exc()})
