# Build TODOs

Keep this file limited to **actionable, still-pending work**. Historical notes and “what changed” belongs in `docs/`.

## Current

- [ ] **Draw/Resign protocol (relay mode)**: resign/draw currently only updates the local database; when an app is connected, protocol-level messaging is required.
  - **Draw request flow**:
    - Investigate how Millennium/Pegasus/Chessnut protocols represent draw offers.
    - Implement offer/accept/decline messaging and UI prompts for incoming offers.
  - **Resign flow**:
    - Investigate how each protocol represents resignation.
    - Implement outgoing resign messaging and handle incoming resign events.
  - **Relevant files**:
    - `src/universalchess/universal.py`
    - `src/universalchess/managers/game/`
    - `src/universalchess/emulators/{millennium,pegasus,chessnut}.py`

## Future / Backlog

- [ ] **Lichess API PGN import (replace Tampermonkey)**: send saved games to Lichess without a browser userscript.
  - Fetch PGN from board web API (e.g. `/getpgn/<id>`).
  - POST to `https://lichess.org/api/import` with `pgn=...`.
  - Open/return the imported game `url` for analysis.
  - Decide whether imports are anonymous or tied to a user token.
