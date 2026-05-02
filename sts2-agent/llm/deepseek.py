"""DeepSeek LLM provider via DeepSeek's Anthropic-compatible endpoint."""

import os
import anthropic
from .base import LLMProvider


class DeepSeekProvider(LLMProvider):
    def __init__(self, model: str = "deepseek-chat", system_prompt: str = "",
                 api_key: str | None = None,
                 base_url: str = "https://api.deepseek.com/anthropic"):
        super().__init__(model, system_prompt)
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
            base_url=base_url,
        )
        self.last_usage: dict | None = None

    def send(self, user_message: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        self.messages.append({"role": "user", "content": user_message})
        return self._call(tools)

    def send_tool_results(self, results: list[dict], tools: list[dict],
                          extra_text: str | None = None) -> tuple[str | None, list[dict]]:
        content = [
            {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
            for r in results
        ]
        if extra_text:
            content.append({"type": "text", "text": extra_text})
        self.messages.append({"role": "user", "content": content})
        return self._call(tools)

    def send_tool_result(self, tool_use_id: str, result: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        return self.send_tool_results([{"tool_use_id": tool_use_id, "content": result}], tools)

    def _call(self, tools: list[dict]) -> tuple[str | None, list[dict]]:
        # DeepSeek's Anthropic-compatible endpoint does not document
        # prompt caching, so we don't attach cache_control markers here.
        kwargs = {
            "model": self.model,
            "max_tokens": 1024,
            "system": self.system_prompt,
            "messages": self.messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}

        response = self.client.messages.create(**kwargs)

        assistant_content = []
        text_response = None
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_response = block.text
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "thinking":
                # DeepSeek reasoner: thinking blocks must be echoed back in
                # subsequent turns or the API rejects the request.
                tb = {"type": "thinking", "thinking": getattr(block, "thinking", "")}
                signature = getattr(block, "signature", None)
                if signature is not None:
                    tb["signature"] = signature
                assistant_content.append(tb)
            elif block.type == "redacted_thinking":
                assistant_content.append({
                    "type": "redacted_thinking",
                    "data": getattr(block, "data", ""),
                })
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
