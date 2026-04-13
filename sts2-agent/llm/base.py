"""Abstract LLM interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # "user", "assistant", "tool_result"
    content: str | list
    tool_use_id: str | None = None
    tool_name: str | None = None


class LLMProvider(ABC):
    """Abstract interface for LLM providers with tool_use support."""

    def __init__(self, model: str, system_prompt: str):
        self.model = model
        self.system_prompt = system_prompt
        self.messages: list[dict] = []

    @abstractmethod
    def send(self, user_message: str, tools: list[dict]) -> tuple[str | None, dict | None]:
        """Send a message and return (text_response, tool_call) where tool_call is
        {"name": str, "input": dict, "id": str} or None if the model responded with text only."""
        ...

    @abstractmethod
    def send_tool_result(self, tool_use_id: str, result: str, tools: list[dict]) -> tuple[str | None, dict | None]:
        """Send the result of a tool call back to the model and get the next response."""
        ...

    def clear_history(self):
        """Clear conversation history (e.g. between acts)."""
        self.messages = []
