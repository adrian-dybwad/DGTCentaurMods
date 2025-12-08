# Simulators

Standalone BLE/RFCOMM servers that emulate chess boards for testing and development. These tools run independently and do not require a physical board.

## Purpose

These simulators serve as working templates that demonstrate how to successfully get chess apps to connect to the Raspberry Pi as each board type. They implement the correct BLE advertisements, GATT services, and protocol responses that each app expects.

Chess apps (Millennium, Chessnut, DGT Pegasus) can connect to these simulators as if they were real boards. Useful for:
- Testing app behavior without hardware
- Protocol development and debugging
- Understanding how real boards respond to commands
- Reference implementations for the universal relay

## Files

| File | Description |
|------|-------------|
| `chessnut.py` | Emulates a Chessnut Air board over BLE with ManufacturerData advertisement |
| `millennium.py` | Emulates a Millennium ChessLink board over BLE and RFCOMM |
| `pegasus.py` | Emulates a DGT Pegasus board using Nordic UART Service |

## Requirements

- Linux with BlueZ (these use D-Bus for Bluetooth)
- Initially designed to run on a PI
- Root or appropriate permissions for BLE advertising

## Usage

Run any simulator as a standalone executable:

```bash
./chessnut.py
./millennium.py
./pegasus.py
```

OR

```
python chessnut.py
python millennium.py
python pegasus.py
```

Then connect your chess app to the advertised device to verify connection and initial piece detection.

## See Also

- `emulators/` - Protocol parsing modules used by the universal relay (not standalone)
