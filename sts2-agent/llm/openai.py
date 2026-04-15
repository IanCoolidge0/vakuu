"""OpenAI LLM provider using the OpenAI SDK."""

import json
from openai import OpenAI
from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4o", system_prompt: str = "",
                 api_key: str | None = None):
        super().__init__(model, system_prompt)
        self.client = OpenAI(api_key=api_key)
        self.last_usage: dict | None = None

    def send(self, user_message: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        self.messages.append({"role": "user", "content": user_message})
        return self._call(tools)

    def send_tool_results(self, results: list[dict], tools: list[dict]) -> tuple[str | None, list[dict]]:
        """Send results for all tool calls. results is [{tool_use_id, content}, ...]"""
        for r in results:
            self.messages.append({
                "role": "tool",
                "tool_call_id": r["tool_use_id"],
                "content": r["content"],
            })
        return self._call(tools)

    # Keep old method for compatibility
    def send_tool_result(self, tool_use_id: str, result: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        return self.send_tool_results([{"tool_use_id": tool_use_id, "content": result}], tools)

    def _call(self, tools: list[dict]) -> tuple[str | None, list[dict]]:
        # Convert Anthropic-style tool schemas to OpenAI function format
        openai_tools = [self._convert_tool(t) for t in tools] if tools else None

        messages = [{"role": "system", "content": self.system_prompt}] + self.messages

        kwargs = {
            "model": self.model,
            "max_completion_tokens": 1024,
            "messages": messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["parallel_tool_calls"] = False

        response = self.client.chat.completions.create(**kwargs)

        message = response.choices[0].message

        # Build assistant message for history
        assistant_msg = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        self.messages.append(assistant_msg)

        usage = getattr(response, "usage", None)
        if usage is not None:
            details = getattr(usage, "prompt_tokens_details", None)
            cache_read = getattr(details, "cached_tokens", 0) if details else 0
            self.last_usage = {
                "input": getattr(usage, "prompt_tokens", 0),
                "output": getattr(usage, "completion_tokens", 0),
                "cache_read": cache_read or 0,
                "cache_creation": 0,  # OpenAI doesn't bill cache writes separately
            }

        # Extract text and tool calls
        text_response = message.content
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments),
                    "id": tc.id,
                })

        return text_response, tool_calls

    @staticmethod
    def _convert_tool(tool: dict) -> dict:
        """Convert Anthropic tool schema to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        }
