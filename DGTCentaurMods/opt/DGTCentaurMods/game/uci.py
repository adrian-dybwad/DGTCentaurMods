"""
Legacy launcher kept for backward-compatible entry points.

Actual implementation lives in `DGTCentaurMods.games.uci`.
"""

from DGTCentaurMods.games.uci import UCIGame, cleanup_and_exit, main

__all__ = ["UCIGame", "cleanup_and_exit", "main"]

if __name__ == "__main__":
    main()
