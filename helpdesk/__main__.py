"""Command line interface.

    python -m helpdesk "How much is an e-bike for a day?"   # one question
    python -m helpdesk                                       # chat with follow-ups
    python -m helpdesk --debug ...                           # also print tool calls
"""

import argparse
import json
import sys

from dotenv import load_dotenv

from helpdesk.agent import Agent, AgentResult
from helpdesk.llm import OpenAICompatibleModel


def print_result(result: AgentResult, debug: bool) -> None:
    if debug:
        for call in result.tool_calls:
            print(f"  [tool] {call.name}({json.dumps(call.arguments, ensure_ascii=False)})")
            print(f"         -> {json.dumps(call.result, ensure_ascii=False)[:300]}")
    print(result.answer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CityWheels help desk agent")
    parser.add_argument("question", nargs="*", help="Question to ask. Leave empty for an interactive chat.")
    parser.add_argument("--debug", action="store_true", help="Print the tool calls and their results.")
    args = parser.parse_args(argv)

    load_dotenv()
    # Windows consoles default to a legacy code page; force UTF-8 for € and non-English replies.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        agent = Agent(OpenAICompatibleModel.from_env())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.question:
        try:
            print_result(agent.ask(" ".join(args.question)), args.debug)
        except Exception as exc:
            print(f"Error: the language model is not reachable ({type(exc).__name__}: {exc}).", file=sys.stderr)
            return 1
        return 0

    print("CityWheels help desk. Ask a question ('/new' starts over, '/quit' exits).")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question in {"/quit", "/exit"}:
            return 0
        if question == "/new":
            agent.reset()
            print("(new conversation)")
            continue
        if question:
            print("Agent: ", end="")
            try:
                print_result(agent.ask(question), args.debug)
            except Exception as exc:  # network/provider errors must not kill the chat
                print(f"Sorry, the language model is not reachable right now ({type(exc).__name__}: {exc}).")


if __name__ == "__main__":
    sys.exit(main())
