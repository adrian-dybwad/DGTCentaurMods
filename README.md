# UNIVERSAL

This project adds features to the DGT Centaur electronic chessboard, such as the ability to export your games via PGN files, use the chessboard as an interface for online play (e.g. Lichess), play engines, and emulate other chess boards such as the DGT Pegasus.

Inside the DGT Centaur is a Raspberry Pi Zero with an SD Card, by replacing that with a Raspberry Pi Zero 2 W (or Raspberry Pi Zero W) and using our own software we get a wireless enabled chessboard that can theoretically do practically anything we can imagine. We've reverse-engineered most of the protocols for piece detection, lights, sound, and display (although we still occasionally discover the odd new thing). Now we can control the board, we're using that to create the software features.

## Architecture

The codebase is built on two foundational layers that enable everything else:

**Serial Communication Layer (`sync_centaur.py`)** - Handles all low-level DGT board protocol: packet parsing, command encoding, and an async callback queue for event processing. This provides a clean, reliable interface to the hardware - piece lift/place events, key presses, LED control, and sound.

**E-Paper Display Framework (`epaper/`)** - A composable widget system with a `Manager`, `Scheduler`, and widget hierarchy (`ChessBoardWidget`, `IconMenuWidget`, `GameAnalysisWidget`, etc.). Handles partial refresh scheduling, framebuffer management, and modal widget support. E-paper displays have unique constraints (slow refresh, ghosting, partial update limitations) and this framework abstracts those complexities away.

These foundations enable the higher-level components:
- `GameManager` receives clean piece events and manages chess game logic
- `DisplayManager` composes widgets without worrying about refresh mechanics  
- The menu system, game resume, position loading - all orchestration on top of solid primitives

Good architecture compounds. Every feature added costs less than it would have before these foundations existed. New capabilities like predefined position loading become mostly wiring - the hard parts (rendering, event handling, correction mode, special move detection) are already solved.

## Development Approach

This codebase was developed through human-AI collaboration - a partnership where each brings different strengths. The human provides domain knowledge, hardware access, real-world testing, and architectural vision. The AI brings pattern recognition across the codebase, rapid iteration on implementations, and the ability to trace complex event flows through multiple layers of abstraction.

The result is code that neither could have written alone. When a bug surfaces - like piece events being delayed during engine thinking - the AI can trace the callback chain from serial parsing through queue workers to blocking calls, while the human provides the runtime logs and hardware feedback that reveal where theory meets reality.

This collaborative approach works because the foundations are solid. Clean abstractions in the serial layer and display framework mean new features can be discussed at the right level of abstraction, implemented correctly the first time, and debugged systematically when issues arise.

**A word of caution!**

**All functionality is based on the fact that the Raspberry Pi Zero inside the board is being replaced with a Raspberry Pi Zero 2 W (or Raspberry Pi Zero W) and this breaks the product warranty. Proceed at your own risk!**

## Project Status and a Word on Forks and Derivatives and other builds

Note on forks and derivatives. As an open source project we want people to be able to take this code and work with it to improve people's experiences with electronic chess boards. You are welcome to amend the code, to use the reversed protocols, to create derivatives, and we encourage you to do so. Whilst we work with the DGT Centaur, maybe you will want to integrate it into your own DIY chessboard, and so on. Hopefully you'll feed back those great changes, fixes, improvements too. We ask only that you follow the license, be clear that your work is a modification, and you ensure that the end user understands the state of the code.

A number of binaries are included in this repository as the software makes use of them - these are not covered under the general GPL license terms of the project. Our GPL license covers the bulk of the Python code. If you are creating a derivative, it is up to you to ensure you can use these binaries. 

This project is presented to you in an beta state. This means that whilst the project works generally, you may come across some bugs. If you have problems, feel free to raise an issue or join us on discord https://discord.gg/zqgUGK2x49 .


## Current Features

### Standalone Play
- **Play Engines** - Play against CT800, Zahak, RodentIV, Maia, or Stockfish directly from the board. Supports takebacks, move overrides, and configurable ELO levels. The engine shows its move via LEDs and you execute it on the board.
- **Game Resume** - If the board is shut down mid-game, it automatically resumes where you left off on next startup.
- **Predefined Positions** - Load test positions (en passant, castling, promotion) or puzzles/endgames from the Settings menu. Physical board correction mode guides you to set up the position correctly.

### Board Emulation (Universal)
The board simultaneously advertises as multiple e-board types and auto-detects which protocol an app uses - this is why it's called UNIVERSAL:
- **DGT Revelation II / Millennium** - Use the Centaur as a Bluetooth DGT e-board with apps, Rabbit plugin, Livechess, etc. Works with Chess for Android and Chess.com app (experimental).
- **DGT Pegasus** - Emulate a DGT Pegasus. Works with the DGT Chess app.
- **Chessnut** - Emulate a Chessnut board for compatible apps.

### Online Play
- **Lichess** - Set your Lichess API token from the web interface, then play online games directly from the board.

### Web Interface
- **Live Board View** - See the current board position at http://IP_ADDRESS or your board's hostname.
- **PGN Download** - Download all played games as PGN files.
- **Game Analysis** - Playback and analyze played games with takeback support.
- **Video Streaming** - Live MJPEG stream at /video for OBS or other streaming setups.
- **Engine Upload** - Upload your own UCI engines via the web interface.

### Connectivity
- **WiFi** - Join WiFi networks from the board (WPS/WPA2).
- **Bluetooth** - Pair with apps via BLE or Bluetooth Classic.
- **Chromecast** - Stream live board view to Chromecast.
- **Network Drive** - Access files via authenticated WebDAV. The last 100 PGNs are accessible as files.

### Settings
- WiFi configuration, Bluetooth pairing, sound control, Lichess API token, engine selection, and predefined position loading.

## Install procedure
See the install procedure in the release info page.
Note: when installing Raspbian please select Bullseye (legacy) and not the new "bookworm".

## Local development setup (configs and database)

- Active config is read from `/opt/universalchess/config/centaur.ini`. A default template is tracked at `packaging/deb-root/opt/universalchess/defaults/config/centaur.ini`.
- To prepare a dev device quickly, run `build/setup.sh` on the Pi. It will:
  - Ensure `/opt/universalchess/config/centaur.ini` exists, copying from `defaults/config/centaur.ini` if missing.
  - Copy resources to `/opt/universalchess/resources/`.
- The SQLite database is created at runtime at `/opt/universalchess/db/centaur.db` on first run; it is not tracked in git.
 - The current FEN position is written to `/opt/universalchess/tmp/fen.log` by runtime services.

## Local Python env (direnv + venv)

- This repo expects the bundled virtualenv at `.venv`. Helper scripts `bin/python` and `bin/pytest` wrap it.
- Auto-activate via direnv:
  1. Install direnv: `brew install direnv`
  2. Ensure shell hook is present:
     ```
     grep -q 'direnv hook zsh' ~/.zshrc || echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
     source ~/.zshrc
     ```
  3. From repo root, allow: `direnv allow`
- After that, entering the repo activates the venv; run tests with `bin/pytest ...` or python with `bin/python ...`.

## Support

Join us on Discord: https://discord.gg/zqgUGK2x49

## Contributors welcome!

If you can offer some time and effort to the project please get in contact! Everybody is more than welcome!
