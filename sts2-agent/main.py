"""Entry point for the STS2 benchmark agent."""

import argparse
import sys
import os
from pathlib import Path

# Force unbuffered output so we see prints in real time
os.environ["PYTHONUNBUFFERED"] = "1"

from client import GameClient
from agent import Agent
from llm.claude import ClaudeProvider
from llm.openai import OpenAIProvider
from llm.deepseek import DeepSeekProvider
from llm.human import HumanProvider
from run_logging import SessionLogger


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
    args = parser.parse_args()

    # Load system prompt
    prompt_path = Path(__file__).parent / "prompts" / "system.txt"
    system_prompt = prompt_path.read_text()
    if not args.verbose:
        if args.provider == "openai":
            system_prompt += "\n\n## Output\nKeep reasoning brief — 1-2 short sentences max, then call the tool."
        else:
            system_prompt += "\n\n## Output\nBe terse. No essays. Just call the tool — at most a single short sentence of reasoning if the decision is non-obvious."

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

    # Create and run agent
    agent = Agent(llm=llm, client=client, verbose=args.verbose, logger=logger)

    BLUE = "\033[34m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"{BLUE}")
    print(f"                  ,--.")
    print(f"         {RED}/\\{BLUE}      / {YELLOW}o o{BLUE} \\      {RED}/\\{BLUE}")
    print(f"        {RED}/ _\\{BLUE}    |  {RED}\\>{BLUE}   |    {RED}/_ \\{BLUE}")
    print(f"       {RED}|/ {BLUE} \\____|  ___  |____/ {RED}  \\|{BLUE}")
    print(f"             /  \\{DIM}######{RESET}{BLUE}/  \\")
    print(f"            /    \\{DIM}####{RESET}{BLUE}/    \\")
    print(f"           (  {CYAN}~~{BLUE}  |{DIM}##{RESET}{BLUE}|  {CYAN}~~{BLUE}  )")
    print(f"            \\    / .. \\    /")
    print(f"          {YELLOW}  $$ {BLUE}/  /  \\  \\{YELLOW} $$")
    print(f"          $${BLUE}  /  /    \\  \\ {YELLOW} $$")
    print(f"         ${BLUE}   \\_/      \\_/{YELLOW}   ${RESET}")
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


if __name__ == "__main__":
    main()
