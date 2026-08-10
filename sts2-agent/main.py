"""Entry point for the STS2 benchmark agent."""

import argparse
import sys
import os
import threading
from pathlib import Path

# Force unbuffered output so we see prints in real time
os.environ["PYTHONUNBUFFERED"] = "1"

# Windows falls back to cp1252 when output is piped; the banner needs UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from client import GameClient
from agent import Agent
from llm.claude import ClaudeProvider
from llm.openai import OpenAIProvider
from llm.deepseek import DeepSeekProvider
from llm.human import HumanProvider
from run_logging import SessionLogger
from tts import TTSToggle

# Vakuu sprite: rows are 16-px left halves, mirrored at render time.
# Rendered 2 pixels per terminal line with ▀/▄ and truecolor ANSI.
_PAL = {
    "k": (24, 26, 38), "s": (72, 84, 122), "S": (108, 126, 176),
    "t": (150, 170, 216), "w": (52, 60, 92), "h": (172, 58, 50),
    "H": (232, 110, 82), "e": (255, 196, 64), "E": (255, 244, 198),
    "b": (216, 88, 48), "c": (96, 224, 214), "C": (54, 140, 148),
    "g": (214, 164, 52), "G": (255, 224, 120),
}

_HALF = [
    "....hh..........",
    "....hHh.........",
    "....hHh.........",
    ".....hHh..kkkkkk",
    ".....hHhkktttttt",
    "......hHkttttttt",
    "......kStkkkkttt",
    "......kSteEEektt",
    "......kSteEEektb",
    "......kSttttttbb",
    "......kStttttttb",
    ".......kSSSSSSSS",
    "....kwwksSSSSSSS",
    "...kwswksSSSSSSS",
    "...kwswksSSSSSSc",
    "...kwswksSSSSScC",
    "...kwswksSSSSScC",
    "...kwswksSSSSSSc",
    "....kwwksSSSSSSS",
    ".....kwkSSSSSSSS",
    "......kkSSSSSSSS",
    "......kgggggGGgg",
    ".....kggGGgggggg",
    "....kkkkkkkkkkkk",
]

# Asymmetric floating glints, applied after mirroring
_GLINTS = {(2, 19): "G", (29, 20): "G", (28, 13): "c", (3, 11): "c"}


def _banner_art(indent="  "):
    rows = []
    for y, half in enumerate(_HALF):
        row = list(half + half[::-1])
        for (x, gy), ch in _GLINTS.items():
            if gy == y:
                row[x] = ch
        rows.append(row)
    lines = []
    for y in range(0, len(rows), 2):
        line, last = [], None
        for t, b in zip(rows[y], rows[y + 1]):
            fg, bg = _PAL.get(t), _PAL.get(b)
            if not fg and not bg:
                ch, colors = " ", (None, None)
            elif fg and bg:
                ch, colors = "▀", (fg, bg)
            elif fg:
                ch, colors = "▀", (fg, None)
            else:
                ch, colors = "▄", (bg, None)
            if colors != last:
                seq = "\033[0m"
                if colors[0]:
                    seq += "\033[38;2;%d;%d;%dm" % colors[0]
                if colors[1]:
                    seq += "\033[48;2;%d;%d;%dm" % colors[1]
                line.append(seq)
                last = colors
            line.append(ch)
        lines.append(indent + "".join(line) + "\033[0m")
    return "\n".join(lines)


def _start_control_listener(agent, llm, tts, base_prompt, terse_suffix):
    """Accept runtime toggles on stdin: `verbose on|off`, `tts on|off`,
    `pause on|off`.

    The high-level control channel for wrappers like gui.py — typing the
    same commands into a terminal run works too. Ends quietly at EOF, so
    piped/detached runs are unaffected. Not started for the human provider,
    which owns stdin."""
    def listen():
        for line in sys.stdin:
            words = line.strip().lower().split()
            if len(words) != 2 or words[1] not in ("on", "off"):
                continue
            name, on = words[0], words[1] == "on"
            if name == "verbose":
                agent.verbose = on
                llm.system_prompt = base_prompt if on else base_prompt + terse_suffix
            elif name == "tts":
                on = tts.set_enabled(on)
            elif name == "pause":
                agent.paused = on
            else:
                continue
            print(f"\033[2m[ctl] {name} {'on' if on else 'off'}\033[0m", flush=True)

    if sys.stdin is not None:
        threading.Thread(target=listen, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="STS2 Benchmark Agent")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Model to use (default: claude-sonnet-4-20250514)")
    parser.add_argument("--provider", default="claude", choices=["claude", "openai", "deepseek", "human"],
                        help="LLM provider (default: claude)")
    parser.add_argument("--url", default="http://localhost:58232",
                        help="Game API URL")
    parser.add_argument("--api-key", default=None,
                        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose LLM reasoning and agent output")
    parser.add_argument("--log-dir", default="logs",
                        help="Directory for session debug logs (default: logs)")
    parser.add_argument("--tts", action="store_true",
                        help="Narrate agent text via Kokoro TTS (requires kokoro-onnx + sounddevice)")
    parser.add_argument("--tts-voice", default="af_sarah",
                        help="Kokoro voice id (default: af_sarah)")
    args = parser.parse_args()

    # Load system prompt. The terse suffix is kept separate so the runtime
    # verbose toggle (see _start_control_listener) can swap it in and out.
    prompt_path = Path(__file__).parent / "prompts" / "system.txt"
    base_prompt = prompt_path.read_text()
    if args.provider == "openai":
        terse_suffix = "\n\n## Output\nKeep reasoning brief — 1-2 short sentences max, then call the tool."
    else:
        terse_suffix = "\n\n## Output\nBe terse. No essays. Just call the tool — at most a single short sentence of reasoning if the decision is non-obvious."
    #system_prompt = base_prompt if args.verbose else base_prompt + terse_suffix
    system_prompt = base_prompt

    # Create LLM provider
    if args.provider == "openai":
        llm = OpenAIProvider(model=args.model, system_prompt=system_prompt, api_key=args.api_key)
    elif args.provider == "deepseek":
        model = args.model if args.model != "claude-sonnet-4-20250514" else "deepseek-chat"
        llm = DeepSeekProvider(model=model, system_prompt=system_prompt, api_key=args.api_key)
    elif args.provider == "human":
        llm = HumanProvider(model="human", system_prompt=system_prompt)
    else:
        llm = ClaudeProvider(model=args.model, system_prompt=system_prompt, api_key=args.api_key)

    # Create game client
    client = GameClient(base_url=args.url)

    # Create session logger
    logger = SessionLogger(log_dir=args.log_dir, model=args.model, provider=args.provider)

    # TTS narration behind a runtime-switchable holder — safe to pass to the
    # agent even when disabled, and the engine loads lazily on first enable.
    tts = TTSToggle(voice=args.tts_voice, enabled=args.tts)

    # Create and run agent
    agent = Agent(llm=llm, client=client, verbose=args.verbose, logger=logger, tts=tts)
    if args.provider != "human":
        _start_control_listener(agent, llm, tts, base_prompt, terse_suffix)

    CYAN = "\033[36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print()
    print(_banner_art())
    print()
    print(f"  {BOLD}{CYAN}V A K U U{RESET}{DIM}  -  STS2 Benchmark Agent{RESET}")
    print(f"  {DIM}Model:  {RESET}{args.model}")
    print(f"  {DIM}Server: {RESET}{args.url}")
    print(f"  {DIM}Log:    {RESET}{logger.path}")
    print()

    try:
        agent.run()
    except KeyboardInterrupt:
        print("\nAgent stopped by user.")
    except Exception as e:
        print(f"\nAgent crashed: {e}")
        logger.error(f"Agent crashed: {e}")
        raise
    finally:
        logger.close()
        if tts:
            tts.stop()


if __name__ == "__main__":
    main()
