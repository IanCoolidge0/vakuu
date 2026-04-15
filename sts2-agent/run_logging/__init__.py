"""Session debug logging for Vakuu agent runs."""

import datetime
import re
from pathlib import Path


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class SessionLogger:
    """Writes a full transcript of the agent session (tool calls, responses, errors)."""

    def __init__(self, log_dir: str | Path = "logs", model: str = "unknown",
                 provider: str = "unknown"):
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = log_path / f"vakuu_{timestamp}.log"
        self._file = open(self.path, "w", encoding="utf-8", buffering=1)
        self._write_header(model, provider)

    def _write_header(self, model: str, provider: str):
        self._file.write(f"=== Vakuu session transcript ===\n")
        self._file.write(f"Started:  {datetime.datetime.now().isoformat()}\n")
        self._file.write(f"Provider: {provider}\n")
        self._file.write(f"Model:    {model}\n")
        self._file.write(f"================================\n\n")

    def _ts(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def write(self, line: str):
        """Write a raw line (stripping ANSI color codes)."""
        clean = ANSI_RE.sub("", line)
        self._file.write(f"[{self._ts()}] {clean}\n")

    def section(self, title: str):
        self._file.write(f"\n--- {title} ---\n")

    def screen(self, screen: str, action_count: int, hp: int | str, gold: int | str, floor: int | str):
        self._file.write(f"\n[{self._ts()}] === SCREEN: {screen} | Floor {floor} | HP {hp} | Gold {gold} | Action #{action_count} ===\n")

    def prompt(self, text: str):
        self._file.write(f"\n[{self._ts()}] PROMPT TO LLM:\n{text}\n")

    def llm_text(self, text: str):
        if text:
            self._file.write(f"\n[{self._ts()}] LLM TEXT: {text}\n")

    def tool_call(self, name: str, inp: dict):
        self._file.write(f"\n[{self._ts()}] TOOL CALL: {name}({inp})\n")

    def tool_result(self, name: str, result: str):
        self._file.write(f"[{self._ts()}] TOOL RESULT ({name}): {result}\n")

    def error(self, msg: str):
        self._file.write(f"\n[{self._ts()}] ERROR: {msg}\n")

    def usage(self, u: dict | None):
        if not u:
            return
        self._file.write(
            f"[{self._ts()}] USAGE: in={u.get('input', 0)} out={u.get('output', 0)} "
            f"cache_read={u.get('cache_read', 0)} cache_creation={u.get('cache_creation', 0)}\n"
        )

    def close(self):
        try:
            self._file.write(f"\n[{self._ts()}] === Session ended ===\n")
            self._file.close()
        except Exception:
            pass
