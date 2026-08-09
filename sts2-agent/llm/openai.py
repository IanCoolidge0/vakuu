"""OpenAI LLM provider using the OpenAI SDK.

Uses the Responses API: reasoning models (gpt-5.x) only support function
tools there, and it works for non-reasoning models too.
"""

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

    def send_tool_results(self, results: list[dict], tools: list[dict],
                          extra_text: str | None = None) -> tuple[str | None, list[dict]]:
        """Send results for all tool calls. If `extra_text` is provided, it's
        appended as a follow-up user message — useful when the action changed
        screens and we want the new screen's prompt in the same round-trip."""
        for r in results:
            self.messages.append({
                "type": "function_call_output",
                "call_id": r["tool_use_id"],
                "output": r["content"],
            })
        if extra_text:
            self.messages.append({"role": "user", "content": extra_text})
        return self._call(tools)

    # Keep old method for compatibility
    def send_tool_result(self, tool_use_id: str, result: str, tools: list[dict]) -> tuple[str | None, list[dict]]:
        return self.send_tool_results([{"tool_use_id": tool_use_id, "content": result}], tools)

    def _call(self, tools: list[dict], _retries: int = 2,
              _spent: dict | None = None) -> tuple[str | None, list[dict]]:
        openai_tools = [self._convert_tool(t) for t in tools] if tools else None

        kwargs = {
            "model": self.model,
            # Reasoning tokens count against this cap, so it needs headroom
            # beyond the visible reply.
            "max_output_tokens": 4096,
            "instructions": self.system_prompt,
            "input": self.messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["parallel_tool_calls"] = False

        response = self.client.responses.create(**kwargs)

        # Keep the raw output items (reasoning, message, function_call) in
        # history — reasoning models require their reasoning items to be sent
        # back alongside function_call_output on the next call.
        n_before = len(self.messages)
        self.messages.extend(response.output)

        usage = getattr(response, "usage", None)
        usage_now = dict(_spent) if _spent else {
            "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        if usage is not None:
            details = getattr(usage, "input_tokens_details", None)
            cache_read = getattr(details, "cached_tokens", 0) if details else 0
            usage_now["input"] += getattr(usage, "input_tokens", 0)
            usage_now["output"] += getattr(usage, "output_tokens", 0)
            usage_now["cache_read"] += cache_read or 0
            # OpenAI doesn't bill cache writes separately, so cache_creation
            # stays 0. Retried attempts fold into one record so the
            # transcript's token accounting stays honest.
        self.last_usage = usage_now

        text_response = response.output_text or None
        tool_calls = []
        for item in response.output:
            if item.type == "function_call":
                try:
                    args = json.loads(item.arguments)
                    parse_error = None
                except json.JSONDecodeError as e:
                    # Degenerate or truncated generation (e.g. the output
                    # cap hit mid-arguments). Keep the call so the
                    # function_call/output pairing stays intact — the agent
                    # returns an error result and the model retries. Raising
                    # here would nuke the whole conversation instead.
                    args = {}
                    parse_error = f"arguments were not valid JSON ({e})"
                call = {"name": item.name, "input": args, "id": item.call_id}
                if parse_error:
                    call["parse_error"] = parse_error
                tool_calls.append(call)

        # Reasoning-only return: hidden reasoning but no message and no tool
        # call. Don't hand this to the agent — it would re-prompt with a
        # duplicate of state the model already saw, which reads like time
        # passed. The API rejects a dangling trailing reasoning item, so we
        # can't resend history as-is either: drop this response's items and
        # re-invoke with the conversation exactly as it was.
        if tools and text_response is None and not tool_calls and _retries > 0:
            del self.messages[n_before:]
            return self._call(tools, _retries - 1, _spent=usage_now)

        return text_response, tool_calls

    @staticmethod
    def _convert_tool(tool: dict) -> dict:
        """Convert Anthropic tool schema to Responses API function format."""
        return {
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {}),
            "strict": False,
        }
