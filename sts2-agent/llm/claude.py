"""Claude LLM provider using the Anthropic SDK."""

import anthropic
from .base import LLMProvider


def _with_last_message_cache_marker(messages: list[dict]) -> list[dict]:
    """Return a copy of `messages` with an ephemeral cache_control marker
    attached to the last content block of the last message. Lets the server
    cache the entire conversation prefix so subsequent turns don't re-process
    earlier history."""
    if not messages:
        return messages
    out = list(messages[:-1])
    last = dict(messages[-1])
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"},
        }]
    elif isinstance(content, list) and content:
        new_content = [dict(b) for b in content]
        new_content[-1]["cache_control"] = {"type": "ephemeral"}
        last["content"] = new_content
    out.append(last)
    return out


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-20250514", system_prompt: str = "",
                 api_key: str | None = None):
        super().__init__(model, system_prompt)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.last_usage: dict | None = None  # {input, output, cache_read, cache_creation}

    def send(self, user_message: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        self.messages.append({"role": "user", "content": user_message})
        return self._call(tools)

    def send_tool_results(self, results: list[dict], tools: list[dict]) -> tuple[str | None, list[dict]]:
        """Send results for all tool calls. results is [{tool_use_id, content}, ...]"""
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
                for r in results
            ]
        })
        return self._call(tools)

    # Keep old method for compatibility
    def send_tool_result(self, tool_use_id: str, result: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        return self.send_tool_results([{"tool_use_id": tool_use_id, "content": result}], tools)

    def _call(self, tools: list[dict]) -> tuple[str | None, list[dict]]:
        # Prompt caching: mark stable prefixes so the server can reuse its
        # processed representation across turns. Cache breakpoints used:
        #  1. End of system prompt
        #  2. End of tool definitions
        #  3. End of the conversation up to (and including) the new message
        system_blocks = [{
            "type": "text",
            "text": self.system_prompt,
            "cache_control": {"type": "ephemeral"},
        }] if self.system_prompt else []

        cached_tools = [dict(t) for t in tools] if tools else []
        if cached_tools:
            cached_tools[-1]["cache_control"] = {"type": "ephemeral"}

        cached_messages = _with_last_message_cache_marker(self.messages)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_blocks if system_blocks else self.system_prompt,
            tools=cached_tools,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            messages=cached_messages,
        )

        # Build assistant message content
        assistant_content = []
        text_response = None
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_response = block.text
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append({
                    "name": block.name,
                    "input": block.input,
                    "id": block.id,
                })
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        self.messages.append({"role": "assistant", "content": assistant_content})

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = {
                "input": getattr(usage, "input_tokens", 0),
                "output": getattr(usage, "output_tokens", 0),
                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            }

        return text_response, tool_calls
