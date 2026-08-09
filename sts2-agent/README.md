# Vakuu — STS2 Benchmark Agent

Named after the Act 3 ancient that autoplays your first turn for you.

```
  ╔═══════════════════════════════════════╗
  ║             V A K U U                 ║
  ║       STS2 Benchmark Agent            ║
  ╚═══════════════════════════════════════╝
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py --model claude-sonnet-4-6 --api-key sk-ant-...
```

Make sure STS2 is running with the mod loaded and a run is active.

## GUI

```bash
python gui.py
```

A thin Tkinter shell around the same terminal harness: it launches `main.py`
as a subprocess and renders its ANSI output as a live trace, with each
thinking block collapsible. Checks for a running game on startup (Refresh to
re-check); provider/model/API key are set per run. The API key field is
required unless the provider's env var is already set.

TTS, verbose, and pause work live mid-run via the agent's stdin control
channel — typing `tts on|off`, `verbose on|off`, or `pause on|off` into a
terminal run does the same (not available with `--provider human`, which
owns stdin). Pause takes effect at the next loop boundary and keeps all
context — resuming picks up exactly where the run left off. Stop is a hard
kill that ends the session.

## Options

```
--model     LLM model ID (default: claude-sonnet-4-20250514)
--url       Game API URL (default: http://localhost:58232)
--api-key   Anthropic API key (or set ANTHROPIC_API_KEY env var)
--quiet     Suppress verbose output
```

## Supported Models

Currently only Claude models via the Anthropic API. Recommended:
- `claude-sonnet-4-6` — best balance of capability and cost
- `claude-haiku-4-5-20251001` — cheapest, good for testing
- `claude-opus-4-6` — most capable, expensive
