# Emulators

Protocol parsing and encoding modules used by `protocol_manager.py` to translate between chess app protocols and the physical board.

## Purpose

These are library modules imported by `protocol_manager.py` (and other relay scripts). They provide:
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
Chess App <--BLE/RFCOMM--> protocol_manager.py <--uses--> emulators/*.py
                                  |
                                  v
                          Physical Centaur Board
```

The ProtocolManager class handles protocol parsing and routing. These emulator modules handle protocol-specific logic.

## Requirements

- Physical board connected
- Used as part of the Universal-Chess system (not standalone)

## See Also

- `tools/simulators/` - Standalone board simulators that run without hardware
- `protocol_manager.py` - The ProtocolManager class that uses these modules
