# Emulators

Protocol parsing and encoding modules used by `game_handler.py` to translate between chess app protocols and the physical DGT Centaur board.

## Purpose

These are library modules imported by `game_handler.py` (and other relay scripts). They provide:
- Protocol packet parsing (decoding commands from apps)
- Response encoding (generating replies in the expected format)
- Board state translation between Centaur and target protocol formats

## Files

| File | Description |
|------|-------------|
| `chessnut.py` | Parses Chessnut Air commands and encodes FEN/battery responses |
| `millennium.py` | Parses Millennium ChessLink packets and encodes responses |
| `pegasus.py` | Parses DGT Pegasus commands and encodes board state |

## Architecture

```
Chess App <--BLE/RFCOMM--> game_handler.py <--uses--> emulators/*.py
                                  |
                                  v
                          Physical Centaur Board
```

The GameHandler class handles Bluetooth stack and routing. These emulator modules handle protocol-specific logic.

## Requirements

- Physical DGT Centaur board connected
- Used as part of the DGTCentaurMods system (not standalone)

## See Also

- `tools/simulators/` - Standalone board simulators that run without hardware
- `game_handler.py` - The GameHandler class that uses these modules
