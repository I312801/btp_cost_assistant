"""
BTP Cost & Usage Intelligence Agent — deployment entry point.

Starts the A2A-compatible HTTP server (FastAPI + uvicorn).
Pass --cli to launch an interactive command-line session instead.

Usage:
    python main.py              # start A2A HTTP server (default)
    python main.py --cli        # interactive CLI mode
    uvicorn server:app --host 0.0.0.0 --port 5001
"""
import argparse
import os
import uvicorn


def run_server() -> None:
    """Start the A2A-compatible FastAPI server."""
    from server import app  # noqa: PLC0415

    port = int(os.getenv("PORT", "5001"))
    uvicorn.run(app, host="0.0.0.0", port=port)


def run_cli() -> None:
    """Launch an interactive CLI session with the BTPUsageAgent."""
    from agent import BTPUsageAgent  # noqa: PLC0415

    print("BTP Cost & Usage Intelligence Agent — CLI mode")
    print("Type your question and press Enter. Type 'exit' or 'quit' to stop.")
    print("Type 'reset' to clear the conversation history.\n")

    agent = BTPUsageAgent()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        if user_input.lower() == "reset":
            agent.reset()
            print("Conversation history cleared.\n")
            continue

        response = agent.chat(user_input)
        print(f"\nAgent: {response}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BTP Cost & Usage Intelligence Agent"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Launch interactive CLI mode instead of the A2A HTTP server.",
    )
    args = parser.parse_args()

    if args.cli:
        run_cli()
    else:
        run_server()
