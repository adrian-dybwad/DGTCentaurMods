# Sniffers

BLE and RFCOMM client analysis tools for reverse-engineering chess board protocols. These connect to real boards as a client to discover services, characteristics, and test protocol communication.

## Files

### chessnut_ble.py
BLE sniffer for Chessnut Air boards. Scans for devices, enumerates services/characteristics, and tests protocol communication.

- **Platform**: Any (uses bleak)
- **Requirements**: `pip install bleak`
- **Use case**: Analyze Chessnut Air BLE protocol, discover advertisement data, test commands

### pegasus_ble.py
BLE sniffer for DGT Pegasus boards. Analyzes Nordic UART Service (NUS) protocol used by Pegasus.

- **Platform**: Any (uses bleak)
- **Requirements**: `pip install bleak`
- **Use case**: Analyze Pegasus BLE protocol, test board state commands, discover responses

### millennium_ble.py
BLE sniffer for Millennium ChessLink boards. Can compare multiple devices advertising as "MILLENNIUM CHESS" to identify differences between real boards and emulators.

- **Platform**: Any (uses bleak)
- **Requirements**: `pip install bleak`
- **Use case**: Analyze Millennium BLE protocol, compare real board vs relay behavior

### millennium_rfcomm.py
Classic Bluetooth (RFCOMM/SPP) sniffer for Millennium ChessLink boards. Tests Serial Port Profile connections.

- **Platform**: Linux with BlueZ
- **Requirements**: Standard socket API (no pip packages)
- **Use case**: Analyze Millennium RFCOMM protocol, compare with BLE behavior

## Usage

All sniffers scan for devices, connect as a client, and perform protocol analysis. Use `--list-all` to see all nearby BLE devices, or `--address` to connect to a specific device.

