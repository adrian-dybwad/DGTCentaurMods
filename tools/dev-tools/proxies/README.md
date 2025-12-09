# Proxies

Man-in-the-middle proxy tools for protocol analysis. These intercept traffic between a chess app and a real board, logging all commands and responses.

## Files

### centaur.py
Serial port proxy for the original DGT Centaur board. Intercepts traffic between the original Centaur software and the physical board via PTY.

- **Platform**: Raspberry Pi
- **Use case**: Monitor what the original Centaur binary sends/receives

### chessnut_ble.py
BLE proxy for Chessnut Air boards. Connects to a real Chessnut Air as a client and advertises as a peripheral for the app to connect to.

- **Platform**: macOS (requires CoreBluetooth)
- **Requirements**: `pip install bleak pyobjc-framework-CoreBluetooth`
- **Use case**: Analyze Chessnut Air protocol by intercepting app-to-board traffic
- **Limitation**: The Chessnut app requires ManufacturerData in the BLE advertisement to discover the board. CoreBluetooth on macOS does not support advertising ManufacturerData, so the Chessnut app cannot discover this proxy. This tool is preserved for reference but is not functional as a proxy.

### pegasus_ble.py
BLE proxy for DGT Pegasus boards. Connects to a real Pegasus as a client and advertises as a peripheral for the DGT app.

- **Platform**: macOS (requires CoreBluetooth)
- **Requirements**: `pip install bleak pyobjc-framework-CoreBluetooth`
- **Use case**: Analyze Pegasus protocol by intercepting app-to-board traffic

## Firmware-based Proxies

### firmware/millennium/
nRF52840 USB Dongle firmware for Millennium ChessLink boards. Unlike the Python-based proxies above, this runs directly on the nRF52840 hardware, allowing full BLE MITM proxying with real-time USB serial output.

- **Platform**: Any computer with USB (Mac, Linux, Windows)
- **Hardware**: nRF52840 USB Dongle
- **Framework**: Zephyr RTOS
- **Use case**: True BLE MITM proxy for Millennium protocol analysis

See [firmware/millennium/README.md](firmware/millennium/README.md) for build and usage instructions.

## Usage

All proxies log bidirectional traffic for protocol reverse-engineering. Run the proxy, then connect your chess app to the proxy instead of the real board.

