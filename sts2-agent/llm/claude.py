"""Claude LLM provider using the Anthropic SDK."""

import anthropic
from .base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-20250514", system_prompt: str = "",
                 api_key: str | None = None):
        super().__init__(model, system_prompt)
        self.client = anthropic.Anthropic(api_key=api_key)

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
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,
            tools=tools,
            messages=self.messages,
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

        return text_response, tool_calls
