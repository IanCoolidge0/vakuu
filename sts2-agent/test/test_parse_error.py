"""OpenAIProvider._call: malformed/truncated function-call arguments must not
raise (a raise nukes the whole conversation) — the call is kept with empty
input and a parse_error flag, and the flagged call counts as a tool call so
the reasoning-only retry does not fire on it."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm.openai import OpenAIProvider


def main():
    provider = OpenAIProvider.__new__(OpenAIProvider)  # skip __init__ (no API key)
    provider.messages = []
    provider.last_usage = None
    provider.system_prompt = ""
    provider.model = "test"

    fc = MagicMock()
    fc.type = "function_call"
    fc.name = "play_card"
    fc.arguments = '{"card_name": "Strike", "target_index'  # truncated mid-key
    fc.call_id = "call_123"

    response = MagicMock()
    response.output = [fc]
    response.output_text = ""
    response.usage = None

    client = MagicMock()
    client.responses.create.return_value = response
    provider.client = client

    text, calls = provider._call(
        [{"name": "play_card", "description": "", "input_schema": {}}])
    assert text is None
    assert len(calls) == 1, calls
    assert calls[0]["input"] == {}
    assert "parse_error" in calls[0], calls[0]
    # No retry fired: exactly one API call
    assert client.responses.create.call_count == 1
    print("provider tolerates truncated arguments:", calls[0]["parse_error"][:60])


if __name__ == "__main__":
    main()
