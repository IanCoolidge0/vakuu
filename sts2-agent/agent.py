"""Main agent loop — polls game state, prompts LLM, executes actions."""

import builtins
import json
import re
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
from compendium import format_keywords_section
from handlers.formatters import (
    format_combat, format_state, format_event, format_card_reward,
    format_rewards, format_rest, format_shop, format_map, format_treasure,
    format_card_select, format_hand_select, fmt_cost, fmt_card_cost, clean_desc,
    card_tags, card_display_name, ench_definitions_section,
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

# Max time the hand-draw animation takes at the start of a turn. A fixed
# wait, not a poll — mid-animation reads can look complete (plausible count,
# stable across reads) while cards are still arriving.
HAND_DRAW_WAIT = 3.0


class Agent:
    def __init__(self, llm: LLMProvider, client: GameClient, verbose: bool = True,
                 logger=None, tts=None):
        self.llm = llm
        self.client = client
        self.verbose = verbose
        self.logger = logger
        self.tts = tts
        self.paused = False  # set via the stdin control listener (main.py)
        self.last_act = 0
        self.action_count = 0
        self.max_actions = 2000  # safety limit per run
        self._last_screen = None
        self._same_screen_count = 0
        self._pending_tool_calls = False
        # Tool results awaiting delivery: set when _take_action exits at a
        # transition boundary; sent together with the next screen's prompt
        # in a single request (see _take_action).
        self._pending_results: list | None = None
        self._pending_reason: str | None = None
        self._keywords_applied = False

    def run(self):
        """Main loop — play until the run ends or we hit the action limit."""
        print(f"{BOLD}Agent starting. Waiting for game connection...{RESET}")
        self.client.health()
        print(f"{GREEN}Connected to STS2.{RESET}")

        while self.action_count < self.max_actions:
            # Pause gate — idles between actions with all context (LLM
            # history, stashed tool results) intact. Takes effect at the
            # next loop boundary, so a pause requested mid-turn lands once
            # the current action settles.
            if self.paused:
                print(f"{DIM}  (paused){RESET}")
                while self.paused:
                    time.sleep(0.3)
                print(f"{DIM}  (resumed){RESET}")

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

            # Append the character's keyword glossary to the system prompt
            # once per run, before the first prompt is sent. The system
            # prompt is the only context that survives history clears, and
            # as a stable prefix it stays cached.
            if not self._keywords_applied and state.get("character"):
                glossary = format_keywords_section(state["character"])
                if glossary:
                    self.llm.system_prompt += "\n\n" + glossary
                self._keywords_applied = True

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
                # Stashed results live inside the history being discarded —
                # drop them with it (no dangling tool_use once cleared).
                self._pending_results = None
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
                if self.tts:
                    self.tts.speak(text)
                    self.tts.wait()
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

    @staticmethod
    def _norm_name(s: str) -> str:
        """Normalize a card name for matching: lowercase, collapsed spaces,
        'name +' → 'name+', 'name [' → 'name['."""
        s = " ".join(s.lower().split())
        return s.replace(" +", "+").replace(" [", "[")

    def _resolve_card_index(self, card_name: str) -> int | None:
        """Resolve a card name to its index in the current hand.

        Display names carry upgrade and enchantment markers —
        'Strike+', 'Strike[Sharp 2]' — so the ladder is:
          1. exact display name (picks a specific copy; a bare name exactly
             matches the unenchanted copy when both exist),
          2. name+upgrade ignoring enchantment brackets (first match),
          3. base name (first match).
        No substring fallback — many card names nest ('Strike' inside
        'Pommel Strike'), and a fuzzy match silently plays the wrong card.
        """
        try:
            hand = self.client.get_combat().get("hand", [])
        except Exception:
            return None
        req = self._norm_name(card_name)
        req_nb = re.sub(r"\[[^\]]*\]$", "", req).strip()
        base = req_nb.rstrip("+").strip()
        displays = [(i, self._norm_name(card_display_name(c)), c)
                    for i, c in enumerate(hand)]
        for i, d, c in displays:
            if d == req:
                return i
        for i, d, c in displays:
            if re.sub(r"\[[^\]]*\]$", "", d) == req_nb:
                return i
        for i, d, c in displays:
            if c["name"].lower() == base:
                return i
        return None

    def _hand_names(self) -> list[str]:
        """Full display names of the cards currently in hand (upgrade and
        enchantment markers included — the names play_card accepts)."""
        try:
            hand = self.client.get_combat().get("hand", [])
            return [card_display_name(c) for c in hand]
        except Exception:
            return []

    def _resolve_hand_select_index(self, card_name: str) -> int | None:
        """Resolve a card name to its index in the pending hand selection options."""
        try:
            state = self.client.get_state()
            cards = state.get("hand_select", {}).get("cards", [])
            req = self._norm_name(card_name)
            base = re.sub(r"\[[^\]]*\]$", "", req).strip().rstrip("+").strip()
            for i, card in enumerate(cards):
                if self._norm_name(card_display_name(card)) == req:
                    return i
            for i, card in enumerate(cards):
                if card["name"].lower() == base:
                    return i
        except Exception:
            pass
        return None

    def _hand_select_names(self) -> list[str]:
        """Names of the cards in the pending hand selection options."""
        try:
            cards = self.client.get_state().get("hand_select", {}).get("cards", [])
            return [c["name"] for c in cards]
        except Exception:
            return []

    def _settle_state(self, timeout: float = 5.0) -> dict | None:
        """Poll until the game reports a stable (non-transition) screen.
        Returns that state, or None if it never settled."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                check = self.client.get_state()
            except Exception:
                time.sleep(0.3)
                continue
            if "error" not in check and check.get("screen") not in ("waiting", "unknown"):
                return check
            time.sleep(0.3)
        return None

    @staticmethod
    def _state_fingerprint(state: dict) -> str:
        """Stable digest of the observable game state, used to detect whether
        a fire-and-forget action actually did anything. Covers same-screen
        effects a screen check misses: rest heals (hp), reward claims (gold /
        potions / relics / rewards list), and events releasing input
        (options list)."""
        rewards = state.get("rewards") or {}
        event = state.get("event") or {}
        keep = {
            "screen": state.get("screen"),
            "hp": state.get("hp"),
            "max_hp": state.get("max_hp"),
            "gold": state.get("gold"),
            "floor": state.get("floor"),
            "act": state.get("act"),
            "potions": [p.get("name") for p in state.get("potions") or []],
            "relics": [r.get("name") for r in state.get("relics") or []],
            "rewards": [r.get("type") for r in rewards.get("rewards") or []],
            "event": [event.get("name"),
                      [o.get("label") for o in event.get("options") or []]],
            "card_select": bool(state.get("card_select")),
            "chest": (state.get("treasure") or {}).get("chest_state"),
        }
        return json.dumps(keep, sort_keys=True, default=str)

    def _settle_transition(self, prev_state: dict,
                           timeout: float = 15.0) -> tuple[dict | None, bool]:
        """Wait for a fire-and-forget action (map click, rest option, reward
        claim, proceed, confirm_selection) to produce an observable result.
        The mod reports success while the game is still animating, so without
        this the LLM gets phantom successes and acts on screens it has never
        seen.

        Returns (new_state, observed): new_state is set if the screen
        changed; observed is True if any effect was seen (screen change, or
        any state diff on the same screen — heal, claim, event closing)."""
        prev_screen = prev_state.get("screen")
        prev_print = self._state_fingerprint(prev_state)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                check = self.client.get_state()
            except Exception:
                time.sleep(0.3)
                continue
            screen = check.get("screen")
            if "error" in check or screen in ("waiting", "unknown"):
                time.sleep(0.3)
                continue
            if screen != prev_screen:
                return check, True
            if self._state_fingerprint(check) != prev_print:
                return None, True
            time.sleep(0.4)
        return None, False

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
                    s += f" ({clean_desc(r['description'])})"
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
                    lines.append(f"  {card_display_name(c)} ({fmt_card_cost(c)}) {card_tags(c)} - {clean_desc(c['description'])}")
                ench_defs = ench_definitions_section(cards)
                if ench_defs:
                    lines.append(ench_defs)
        except Exception:
            pass

        return "\n".join(lines)

    def _build_prompt(self, screen: str, state: dict) -> str:
        match screen:
            case "combat":
                try:
                    time.sleep(HAND_DRAW_WAIT)
                    combat = self.client.get_combat()
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
        """Send prompt to LLM, handle tool calls in a loop.

        If the previous _take_action exited at a transition boundary, its
        stashed tool results ride along with this screen's prompt in one
        request — same round-trip count as in-loop piggybacking, but control
        returns to the main loop at every transition."""
        if self._pending_results is not None:
            pending = self._pending_results
            reason = self._pending_reason
            self._pending_results = None
            self._pending_reason = None
            if reason == "turn_ended":
                preamble = ("Your turn ended and the enemies have acted. "
                            "Here is the new turn:\n\n")
            else:
                preamble = (f"The game transitioned to a new screen ({screen}). "
                            "Act on the new screen using its tools:\n\n")
            full_prompt = preamble + prompt
            if self.logger:
                self.logger.prompt(full_prompt)
            try:
                text, tool_calls = self.llm.send_tool_results(
                    pending, tools, extra_text=full_prompt)
            except Exception as e:
                print(f"{RED}LLM error: {e}{RESET}")
                print(f"{YELLOW}Clearing conversation history to recover...{RESET}")
                if self.logger:
                    self.logger.error(f"LLM error (send pending): {e}")
                self.llm.clear_history()
                return
            return self._run_tool_loop(text, tool_calls, tools, screen, state)

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
        return self._run_tool_loop(text, tool_calls, tools, screen, state)

    def _run_tool_loop(self, text, tool_calls, tools: list[dict],
                       screen: str, state: dict):
        """Execute tool calls until the model stops, a transition boundary is
        reached (results get stashed for the next _take_action), or the
        runaway backstop trips."""
        if text:
            print(f"{MAGENTA}{text}{RESET}")
            if self.tts:
                self.tts.speak(text)
        if self.logger:
            self.logger.llm_text(text)
            self.logger.usage(getattr(self.llm, "last_usage", None))
        # Let the narration of this turn's reasoning finish before the
        # corresponding tool calls fire.
        if self.tts:
            self.tts.wait()

        # With boundary exits, one loop spans at most a single turn or one
        # screen's worth of actions — the cap is purely a runaway backstop.
        max_tool_rounds = 30
        self._pending_tool_calls = False
        for _ in range(max_tool_rounds):
            if not tool_calls:
                self._pending_tool_calls = False
                break

            self._pending_tool_calls = True

            # Execute all tool calls and collect results
            results = []
            screen_changed = False
            turn_ended = False
            for tool_call in tool_calls:
                name = tool_call['name']
                inp = tool_call['input']
                inp_str = ", ".join(f"{k}={v}" for k, v in inp.items()) if inp else ""

                # Once a transition is detected, executing the rest of the
                # batch would act blindly on a screen the LLM hasn't seen
                # (e.g. a queued proceed firing into a just-opened shop).
                if screen_changed:
                    result = json.dumps({"error":
                        "Cancelled — the game state changed after the previous "
                        "action. Re-decide using the new state."})
                    print(f"  {DIM}>>> {name}({inp_str}) [cancelled — state changed]{RESET}")
                    if self.logger:
                        self.logger.tool_call(name, inp)
                        self.logger.tool_result(name, result)
                    results.append({"tool_use_id": tool_call['id'], "content": result})
                    continue

                # The provider flags calls whose arguments didn't parse
                # (truncated/degenerate generation). Reject with feedback
                # instead of executing with empty input.
                if tool_call.get("parse_error"):
                    result = json.dumps({"error":
                        f"Call to {name} rejected — {tool_call['parse_error']}. "
                        "The generation was likely truncated; re-issue the "
                        "call with concise, valid arguments."})
                    print(f"  {RED}>>> {name}(<unparseable args>) [rejected]{RESET}")
                    if self.logger:
                        self.logger.tool_call(name, {"parse_error": tool_call["parse_error"]})
                        self.logger.tool_result(name, result)
                    results.append({"tool_use_id": tool_call['id'], "content": result})
                    continue

                # proceed is valid on every screen, so it can fire into a
                # screen the model has never seen (e.g. a rewards screen
                # appearing right after a kill). Abort only when the live
                # screen is one proceed can skip through — on map/combat/
                # event screens it's harmless or is itself the recovery
                # action (closing a lingering event that swallows map input).
                _proceed_skippable = {"rewards", "shop", "rest", "treasure",
                                      "card_reward", "card_select", "hand_select"}
                if name == "proceed":
                    try:
                        live_state = self.client.get_state()
                    except Exception:
                        live_state = None
                    live = live_state.get("screen") if live_state else None
                    if (live_state is not None and "error" not in live_state
                            and live != screen and live in _proceed_skippable):
                        result = json.dumps({"error":
                            f"Proceed aborted — the screen changed since your "
                            f"last prompt (was '{screen}', now '{live}'). "
                            "Act on the new state."})
                        print(f"  {DIM}>>> proceed() [aborted — screen is now {live}]{RESET}")
                        if self.logger:
                            self.logger.tool_call(name, inp)
                            self.logger.tool_result(name, result)
                        screen_changed = True
                        results.append({"tool_use_id": tool_call['id'], "content": result})
                        continue

                print(f"  {BOLD}{GREEN}>>> {name}({inp_str}){RESET}")
                if self.logger:
                    self.logger.tool_call(name, inp)

                try:
                    result = self._execute_tool(tool_call, screen, state)
                    self.action_count += 1
                except Exception as e:
                    result = json.dumps({"error": str(e)})

                result_data = None
                success = False
                try:
                    result_data = json.loads(result)
                    success = isinstance(result_data, dict) and bool(result_data.get("success"))
                except (json.JSONDecodeError, TypeError):
                    pass

                # Detect state transitions so the LLM never acts blind:
                #  - end_turn resolves the enemy turn synchronously behind the
                #    call — always hand back the new turn (or the post-combat
                #    screen), otherwise the model plays cards into a turn it
                #    has never seen, or blind-ends it entirely.
                #  - play_card / use_potion / select_hand_card may change
                #    screens (kill → rewards, Armaments → hand_select).
                #  - choose_map_node / choose_rest_option / proceed /
                #    confirm_selection are fire-and-forget in the mod: success
                #    returns while the game is still transitioning, so wait
                #    for the outcome to become observable before continuing.
                if success and name == "end_turn":
                    check = self._settle_state(timeout=8.0)
                    if check is not None:
                        screen_changed = True
                        turn_ended = check.get("screen") == "combat"
                elif success and name in ("play_card", "use_potion",
                                          "select_hand_card", "select_card"):
                    # select_card is included because choose-type overlays
                    # (e.g. Colorless Potion) auto-confirm on selection — the
                    # screen moves on without a confirm_selection. On grid
                    # overlays (Smith) the screen is stable and this returns
                    # immediately.
                    check = self._settle_state(timeout=5.0)
                    if check is not None and check.get("screen") != screen:
                        screen_changed = True
                    elif isinstance(result_data, dict):
                        # Report the hand after the play. Draws, exhausts and
                        # generated cards are otherwise invisible until the
                        # next turn prompt — a human sees their hand at all
                        # times, and the model can't derive hidden draws.
                        # Contents only, no derived outcomes.
                        hand = self._hand_names()
                        if hand:
                            result_data["hand"] = hand
                            result = json.dumps(result_data)
                elif success and name in ("choose_map_node", "choose_rest_option",
                                          "claim_reward", "proceed", "skip_rewards",
                                          "confirm_selection"):
                    # Claiming a card reward opens the card_reward screen
                    # after a transition that can run long — give it headroom.
                    settle_timeout = 20.0 if name == "claim_reward" else 15.0
                    settled, observed = self._settle_transition(
                        state, timeout=settle_timeout)
                    if settled is not None:
                        screen_changed = True
                    elif observed:
                        # Same-screen effect landed (heal, claim, event
                        # closing). Refresh the baseline so the next settled
                        # action compares against current reality.
                        try:
                            state = self.client.get_state()
                        except Exception:
                            pass
                    else:
                        warning = (
                            f"No state change was observed within "
                            f"{int(settle_timeout)}s — the action may not have "
                            "registered. A previous screen (e.g. an event) may "
                            "still be open and swallowing input — proceed can "
                            "close it. Verify with view_map/view_deck before "
                            "repeating this action.")
                        if name == "choose_map_node":
                            # The usual culprit is a finished event whose
                            # pending (invisible) proceed button still
                            # swallows map clicks while get_state reports
                            # "map". The mod's proceed clicks it regardless
                            # of visibility — try that recovery directly,
                            # but only while the screen still reads "map"
                            # (never into a room that just finished loading).
                            try:
                                cur = self.client.get_state()
                                rec = (self.client.proceed()
                                       if cur.get("screen") == "map" else None)
                                if isinstance(rec, dict) and rec.get("success"):
                                    warning = (
                                        "The map click did not register — a "
                                        "lingering screen was swallowing input "
                                        f"({rec.get('message')}). It has been "
                                        "closed; retry your selection now.")
                            except Exception:
                                pass
                        result_data["warning"] = warning
                        result = json.dumps(result_data)

                if self.logger:
                    self.logger.tool_result(name, result)

                # Check for errors to show
                if isinstance(result_data, dict) and result_data.get("error"):
                    print(f"  {RED}!!! {result_data['error']}{RESET}")

                results.append({"tool_use_id": tool_call['id'], "content": result})

            # Transition boundary: stash the results and hand control back
            # to the main loop, which delivers them together with the new
            # screen's prompt in a single request. Same round-trip count as
            # in-loop piggybacking, but the loop exits at every transition,
            # so history clearing and screen tracking keep working.
            if screen_changed:
                self._pending_results = results
                self._pending_reason = "turn_ended" if turn_ended else "screen_changed"
                self._pending_tool_calls = False
                return

            # Always send all results back - never leave dangling tool_use blocks
            try:
                text, tool_calls = self.llm.send_tool_results(results, tools)
                self._pending_tool_calls = bool(tool_calls)
            except Exception as e:
                print(f"{RED}LLM error on tool result: {e}{RESET}")
                # Conversation is now broken — clear history to recover
                print(f"{YELLOW}Clearing conversation history to recover...{RESET}")
                if self.logger:
                    self.logger.error(f"LLM error (send_tool_results): {e}")
                self.llm.clear_history()
                self._pending_tool_calls = False
                # The current batch was already executed and its results died
                # with the cleared history — emptying tool_calls keeps the
                # leftover-cancellation block from re-cancelling them into
                # the fresh conversation with a bogus cap message.
                tool_calls = []
                break

            if text:
                print(f"{MAGENTA}{text}{RESET}")
                if self.tts:
                    self.tts.speak(text)
            if self.logger:
                self.logger.llm_text(text)
                self.logger.usage(getattr(self.llm, "last_usage", None))
            # Wait for narration before the next round of tool calls fires.
            if self.tts:
                self.tts.wait()

        # If the loop exited with pending tool_use blocks (max rounds,
        # screen change, etc.), send cancellation results to close them
        # properly instead of nuking the entire conversation history.
        # Critically, pass tools=[] so the model's response is guaranteed
        # text-only — otherwise it may emit another tool_use in reply to
        # the cancellation, leaving a new dangling tool_use that will
        # brick the next turn and force a catastrophic history clear.
        if tool_calls:
            cancelled_names = ", ".join(tc['name'] for tc in tool_calls)
            print(f"{YELLOW}Tool round cap reached — cancelling: {cancelled_names}{RESET}")
            if self.logger:
                self.logger.error(
                    f"Tool round cap ({max_tool_rounds}) reached — "
                    f"cancelled pending call(s): {cancelled_names}")
            dummy_results = [
                {"tool_use_id": tc['id'],
                 "content": json.dumps({"error": "Action cancelled — the harness "
                     "is refreshing the game state; it will be provided next."})}
                for tc in tool_calls
            ]
            try:
                text, leftover = self.llm.send_tool_results(dummy_results, [])
                if self.logger:
                    self.logger.llm_text(text)
                    self.logger.usage(getattr(self.llm, "last_usage", None))
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
                            hand = self._hand_names()
                            return json.dumps({"error":
                                f"Card '{card_name}' is not in your hand. "
                                f"Current hand: {hand if hand else 'unavailable'}"})
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
                case "skip_rewards":
                    result = self.client.skip_rewards()
                case "proceed":
                    result = self.client.proceed()

                # Rest site
                case "choose_rest_option":
                    result = self.client.choose_rest_option(inp["option_index"])

                # Shop
                case "shop_buy":
                    item_name = inp.get("item_name") or inp.get("name")
                    if not item_name:
                        return json.dumps({"error": "shop_buy requires item_name."})
                    result = self.client.shop_buy(item_name)
                case "shop_remove_card":
                    result = self.client.shop_remove_card()

                # In-combat hand card selection (e.g. Armaments, Acrobatics)
                case "select_hand_card":
                    card_name = inp.get("card_name")
                    if not card_name:
                        return json.dumps({"error": "select_hand_card requires card_name."})
                    card_index = self._resolve_hand_select_index(card_name)
                    if card_index is None:
                        options = self._hand_select_names()
                        return json.dumps({"error":
                            f"Card '{card_name}' not in selection options. "
                            f"Options: {options if options else 'unavailable'}"})
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
                        lines.append(f"  [{i}] {card_display_name(c)} ({fmt_card_cost(c)}) {card_tags(c)}")
                    ench_defs = ench_definitions_section(cards)
                    if ench_defs:
                        lines.append("\n" + ench_defs)
                    return "\n".join(lines)
                case "view_map":
                    map_data = self.client.get_map()
                    return format_map(map_data)
                case "view_draw_pile":
                    piles = self.client.get_combat_piles()

                    def pile_line(c):
                        return f"  {card_display_name(c)} ({fmt_card_cost(c)}) {card_tags(c)}"

                    lines = [f"Draw pile ({piles['draw_pile_count']}):"]
                    for c in piles['draw_pile']:
                        lines.append(pile_line(c))
                    lines.append(f"\nDiscard pile ({len(piles['discard_pile'])}):")
                    for c in piles['discard_pile']:
                        lines.append(pile_line(c))
                    if piles['exhaust_pile']:
                        lines.append(f"\nExhaust pile ({len(piles['exhaust_pile'])}):")
                        for c in piles['exhaust_pile']:
                            lines.append(pile_line(c))
                    all_cards = (piles['draw_pile'] + piles['discard_pile']
                                 + piles['exhaust_pile'])
                    ench_defs = ench_definitions_section(all_cards)
                    if ench_defs:
                        lines.append("\n" + ench_defs)
                    return "\n".join(lines)

                case _:
                    return json.dumps({"error": f"Unknown tool: {name}"})

            return json.dumps(result)

        except Exception as e:
            return json.dumps({"error": str(e), "traceback": traceback.format_exc()})
