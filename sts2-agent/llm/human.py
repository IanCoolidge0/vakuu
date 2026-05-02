"""Human player adapter — the human IS the LLM. Useful for debugging tool
schemas and prompt formatting by feeling out the agent's perspective directly.

Usage at the prompt:
  <tool_name> [key=value ...]      e.g.  play_card card_name=Strike target_index=0
  <tool_name> {"key": value, ...}  raw JSON args also accepted
  ?                                 list tools available on this screen
  ?<tool_name>                      show that tool's input schema
  .                                 reply with text only (no tool call)
  q                                 raise KeyboardInterrupt to quit cleanly

Quoting: shell-style. e.g.  shop_buy slot_index=2  /  play_card card_name="Searing Blow"
"""

import json
import shlex
import sys
import uuid
from .base import LLMProvider


CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _coerce(v: str):
    """Best-effort scalar coercion for key=value args."""
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.lower() == "null":
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    # Strip surrounding quotes if present (shlex usually handles this)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def _print_tools(tools: list[dict]):
    if not tools:
        print(f"{DIM}(no tools available on this screen){RESET}")
        return
    print(f"{BOLD}Available tools:{RESET}")
    for t in tools:
        name = t["name"]
        desc = t.get("description", "")
        # Compress to a single line
        first_line = desc.splitlines()[0] if desc else ""
        print(f"  {GREEN}{name}{RESET}  {DIM}{first_line}{RESET}")


def _print_tool_schema(tools: list[dict], name: str):
    for t in tools:
        if t["name"] == name:
            print(f"{BOLD}{t['name']}{RESET}")
            if t.get("description"):
                print(f"  {t['description']}")
            schema = t.get("input_schema", {})
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            if not props:
                print(f"  {DIM}(no parameters){RESET}")
            else:
                print(f"  Parameters:")
                for k, v in props.items():
                    req = " (required)" if k in required else ""
                    typ = v.get("type", "?")
                    d = v.get("description", "")
                    print(f"    {GREEN}{k}{RESET}: {typ}{req} — {DIM}{d}{RESET}")
            return
    print(f"{RED}No such tool: {name}{RESET}")


def _parse_input(line: str, tools: list[dict]) -> tuple[str, dict] | None:
    """Parse a user input line into (tool_name, args) or None if no tool call."""
    line = line.strip()
    if not line or line == ".":
        return None

    # Optional: "name {json}" form
    space = line.find(" ")
    if space != -1:
        rest = line[space + 1:].lstrip()
        if rest.startswith("{"):
            name = line[:space].strip()
            try:
                args = json.loads(rest)
                if not isinstance(args, dict):
                    raise ValueError("args must be an object")
                return name, args
            except Exception as e:
                raise ValueError(f"invalid JSON args: {e}")

    # key=value form
    try:
        parts = shlex.split(line)
    except ValueError as e:
        raise ValueError(f"unparseable input: {e}")
    if not parts:
        return None
    name = parts[0]
    args: dict = {}
    for p in parts[1:]:
        if "=" not in p:
            raise ValueError(f"expected key=value, got: {p!r}")
        k, _, v = p.partition("=")
        args[k.strip()] = _coerce(v)
    return name, args


class HumanProvider(LLMProvider):
    """LLM provider where the human types tool calls at the terminal."""

    def __init__(self, model: str = "human", system_prompt: str = "",
                 api_key: str | None = None):
        super().__init__(model, system_prompt)
        self.last_usage: dict | None = None
        self._counter = 0

    def send(self, user_message: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        # Print the screen prompt — this is what the LLM would see
        print()
        print(f"{CYAN}{'═' * 60}{RESET}")
        print(user_message)
        print(f"{CYAN}{'═' * 60}{RESET}")
        return self._prompt(tools)

    def send_tool_results(self, results: list[dict], tools: list[dict],
                          extra_text: str | None = None) -> tuple[str | None, list[dict]]:
        # Echo tool results back so the human sees what their action did
        print()
        for r in results:
            content = r["content"]
            # Try to pretty-print JSON, else dump raw
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("error"):
                    print(f"  {RED}!! {parsed['error']}{RESET}")
                else:
                    print(f"  {DIM}{json.dumps(parsed, indent=2)[:500]}{RESET}")
            except (json.JSONDecodeError, TypeError):
                print(f"  {DIM}{str(content)[:500]}{RESET}")
        if extra_text:
            print()
            print(f"{CYAN}--- (screen changed) ---{RESET}")
            print(extra_text)
            print(f"{CYAN}{'─' * 60}{RESET}")
        return self._prompt(tools)

    def send_tool_result(self, tool_use_id: str, result: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        return self.send_tool_results([{"tool_use_id": tool_use_id, "content": result}], tools)

    def _prompt(self, tools: list[dict]) -> tuple[str | None, list[dict]]:
        tool_index = {t["name"]: t for t in tools}
        while True:
            try:
                line = input(f"{BOLD}you>{RESET} ").strip()
            except EOFError:
                raise KeyboardInterrupt
            if line == "q":
                raise KeyboardInterrupt

            if line == "?" or line.startswith("? "):
                _print_tools(tools)
                continue
            if line.startswith("?"):
                _print_tool_schema(tools, line[1:].strip())
                continue

            try:
                parsed = _parse_input(line, tools)
            except ValueError as e:
                print(f"{RED}{e}{RESET}")
                continue

            if parsed is None:
                # No tool call — return text-only (mirrors LLM saying nothing)
                return None, []

            name, args = parsed
            if name not in tool_index:
                print(f"{RED}Unknown tool: {name}{RESET}  {DIM}('?' to list tools){RESET}")
                continue

            self._counter += 1
            tool_call = {
                "name": name,
                "input": args,
                "id": f"human_{self._counter}_{uuid.uuid4().hex[:6]}",
            }
            return None, [tool_call]
