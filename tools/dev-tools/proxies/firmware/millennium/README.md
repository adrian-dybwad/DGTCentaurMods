# Millennium BLE Proxy Firmware

nRF52840 USB Dongle firmware that acts as a BLE man-in-the-middle proxy between
a chess app and a real Millennium ChessLink board.

## Overview

```
┌─────────────────┐     BLE      ┌──────────────────┐     BLE      ┌─────────────┐
│   Chess App     │◄────────────►│   nRF52840       │◄────────────►│  Millennium │
│                 │              │   USB Dongle     │              │  ChessLink  │
└─────────────────┘              │                  │              └─────────────┘
                                 │  ┌────────────┐  │
                                 │  │ Peripheral │  │  (fake board)
                                 │  ├────────────┤  │
                                 │  │  Central   │  │  (connects to real board)
                                 │  └────────────┘  │
                                 │        │         │
                                 │    USB CDC      │
                                 └────────┬────────┘
                                          │
                                          ▼
                                 ┌─────────────────┐
                                 │  Host Computer  │
                                 │  (Mac/Linux)    │
                                 │  - Real-time    │
                                 │    protocol log │
                                 └─────────────────┘
```

The proxy:
1. **Peripheral role**: Advertises as "MILLENNIUM CHESS" for chess apps to connect
2. **Central role**: Scans for and connects to the real Millennium board
3. **USB CDC**: Streams all traffic to the host computer with timestamps

All traffic is forwarded transparently - the app thinks it's talking to the
real board, and the board thinks it's talking to the app.

## Hardware

- **nRF52840 USB Dongle** (Nordic PCA10059 or compatible)
- Real Millennium ChessLink board (or compatible: Chess Genius Exclusive, The King, etc.)

## Building

### Prerequisites

1. Install Zephyr SDK and tools:
   ```bash
   # macOS
   brew install cmake ninja gperf python3 ccache qemu dtc
   pip3 install west

   # Set up Zephyr
   west init ~/zephyrproject
   cd ~/zephyrproject
   west update
   west zephyr-export
   pip3 install -r ~/zephyrproject/zephyr/scripts/requirements.txt
   ```

2. Install nRF Command Line Tools for flashing:
   - Download from: https://www.nordicsemi.com/Products/Development-tools/nRF-Command-Line-Tools

### Build

```bash
# Set Zephyr environment
source ~/zephyrproject/zephyr/zephyr-env.sh

# Navigate to this directory
cd tools/dev-tools/proxies/firmware/millennium

# Build for nRF52840 USB Dongle
west build -b nrf52840dongle .
```

### Flash

The nRF52840 USB Dongle uses a built-in bootloader. To flash:

1. Put dongle in bootloader mode:
   - Press the reset button while plugging in USB
   - OR press the reset button and hold SW1 (if available)
   - The LED should pulse slowly

2. Flash the firmware:
   ```bash
   # Using nrfutil (recommended)
   nrfutil pkg generate --hw-version 52 --sd-req=0x00 \
       --application build/zephyr/zephyr.hex \
       --application-version 1 millennium_proxy.zip
   nrfutil dfu usb-serial -pkg millennium_proxy.zip -p /dev/tty.usbmodem*

   # OR using nRF Connect for Desktop (Programmer app)
   ```

## Usage

1. Flash the firmware to the nRF52840 dongle
2. Plug the dongle into your Mac
3. Find the USB serial port:
   ```bash
   ls /dev/tty.usbmodem*
   ```

4. Open a terminal to view traffic:
   ```bash
   # Using screen
   screen /dev/tty.usbmodem* 115200

   # Using Python
   python3 -m serial.tools.miniterm /dev/tty.usbmodem* 115200
   ```

5. Turn on your real Millennium board (it will be discovered automatically)

6. Connect your chess app to "MILLENNIUM CHESS" (the proxy)

7. Watch the protocol traffic stream in real-time:
   ```
   ============================================
     Millennium BLE Proxy
     nRF52840 USB Dongle Firmware
   ============================================

   [00:00:01.234] STATUS: Bluetooth initialized
   [00:00:01.345] STATUS: Advertising as 'MILLENNIUM CHESS' - waiting for app...
   [00:00:01.456] STATUS: Scanning for real Millennium board...
   [00:00:03.789] STATUS: Found Millennium board: XX:XX:XX:XX:XX:XX (RSSI: -45)
   [00:00:04.012] STATUS: Connected to real Millennium board
   [00:00:04.234] STATUS: Subscribed to real board notifications
   [00:00:15.678] STATUS: Chess app connected: YY:YY:YY:YY:YY:YY
   [00:00:15.890] STATUS: App subscribed to TX notifications
   [00:00:16.012] APP->BOARD: 57  (CMD: SCAN ON)
   [00:00:16.123] BOARD->APP: 72  (RESP: ACK)
   [00:00:16.234] APP->BOARD: 53  (CMD: BOARD STATE request)
   [00:00:16.345] BOARD->APP: 73 2e 2e 2e ...  (RESP: BOARD STATE ...)
   ```

## LED Status

- **Off**: No Bluetooth
- **Slow blink** (1Hz): Scanning/advertising, no connections
- **Fast blink** (5Hz): One connection established
- **Solid on**: Both connections active - proxy fully operational

## Protocol Notes

The Millennium ChessLink uses a simple ASCII-based protocol:
- Commands use uppercase letters (V, S, L, X, R, B, W, I)
- Responses use lowercase letters (v, s, r)
- Each byte has 7-bit parity (MSB)
- Messages end with XOR CRC

Common commands:
- `V` - Version request → `v` + version string
- `S` - Board state request → `s` + 64 chars (one per square)
- `L` + square + state - Set LED
- `X` - All LEDs off
- `W` - Enable board scanning
- `I` - Disable board scanning

## Files

```
millennium/
├── CMakeLists.txt              # Zephyr build configuration
├── prj.conf                    # Zephyr project settings
├── boards/
│   └── nrf52840dongle_nrf52840.overlay  # Device tree overlay
├── src/
│   ├── main.c                  # Application entry point
│   ├── ble_central.c/h         # Central role (connects to real board)
│   ├── ble_peripheral.c/h      # Peripheral role (accepts app connections)
│   ├── usb_console.c/h         # USB CDC output
│   └── protocol.c/h            # Protocol definitions and decoding
└── README.md                   # This file
```

## Troubleshooting

### Dongle not detected
- Make sure it's in bootloader mode (pulsing LED)
- Try a different USB port
- Check `dmesg` or Console.app for USB errors

### Can't find real board
- Make sure the real board is powered on
- Check the board name in the serial output
- Real board should advertise as "MILLENNIUM CHESS"

### App can't find proxy
- Check that advertising is active (see serial output)
- Some apps may cache old Bluetooth pairings - clear them
- Try restarting Bluetooth on your phone

### No traffic visible
- Ensure both central and peripheral are connected (solid LED)
- Check that the app is actually communicating
- Make sure USB CDC console is working (test with `echo` command in shell)

