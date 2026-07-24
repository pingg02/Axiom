"""
Reasonix — AI coding agent.

Usage:
  python -m reasonix chat            Interactive REPL
  python -m reasonix run <prompt>     Single prompt
  python -m reasonix serve            HTTP/SSE server
  python -m reasonix desktop          WebSocket desktop bridge
  python -m reasonix <prompt>         Quick prompt (no "run" needed)
  python -m reasonix --version        Print version
"""

from reasonix.cli.cli import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
