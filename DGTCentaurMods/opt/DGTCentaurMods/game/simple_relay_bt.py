# Proxy/Relay between Bluetooth Serial and Hardware Serial
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import serial
import time
import threading
import bluetooth
import os
import psutil
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController
from DGTCentaurMods.board.settings import Settings

# Initialize serial connection like board.py (directly, not through SyncCentaur)
# This is the same initialization as in SyncCentaur._initialize()
# Note: We don't import epaper to avoid triggering board.py initialization
# which would create a conflicting SyncCentaur controller
log.info("Initializing serial connection...")
dev = Settings.read('system', 'developer', 'False')
developer_mode = dev.lower() == 'true'

if developer_mode:
    log.debug("Developer mode enabled - setting up virtual serial port")
    os.system("socat -d -d pty,raw,echo=0 pty,raw,echo=0 &")
    time.sleep(10)
    ser = serial.Serial("/dev/pts/2", baudrate=1000000, timeout=5.0)
else:
    try:
        ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)
        ser.isOpen()
    except:
        ser.close()
        ser.open()

log.info("Serial port opened successfully")
log.info("Waiting for Bluetooth connection...")

# Create Bluetooth controller instance and start pairing thread
bluetooth_controller = BluetoothController()
pairThread = bluetooth_controller.start_pairing_thread()

# Kill rfcomm if it is started (same as eboard.py)
os.system('sudo service rfcomm stop')
time.sleep(2)
for p in psutil.process_iter(attrs=['pid', 'name']):
    if str(p.info["name"]) == "rfcomm":
        p.kill()
iskilled = 0
log.info("checking killed")
while iskilled == 0:
    iskilled = 1
    for p in psutil.process_iter(attrs=['pid', 'name']):
        if str(p.info["name"]) == "rfcomm":
            iskilled = 0
    time.sleep(0.1)

kill = 0

# Initialize Bluetooth serial like eboard.py
server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
server_sock.bind(("", bluetooth.PORT_ANY))
server_sock.settimeout(0.5)
server_sock.listen(1)
port = server_sock.getsockname()[1]
uuid = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
bluetooth.advertise_service(server_sock, "UARTClassicServer", service_id=uuid,
                            service_classes=[uuid, bluetooth.SERIAL_PORT_CLASS],
                            profiles=[bluetooth.SERIAL_PORT_PROFILE])

log.info("Waiting for connection on RFCOMM channel: " + str(port))
connected = 0
while connected == 0 and kill == 0:
    try:
        bt, client_info = server_sock.accept()
        connected = 1
    except:
        # Check for BACK button (we'll need to poll the board differently)
        # For now, just sleep
        time.sleep(0.1)

if kill == 1:
    log.info("Exiting...")
    time.sleep(1)
    os._exit(0)

log.info("Connected")
log.info("Relay active")

# Relay state
running = True

def bt_to_serial():
    """Relay data from Bluetooth to Serial"""
    global running, bt, ser
    log.info("Starting BT -> Serial relay thread")
    try:
        while running:
            try:
                # Read from Bluetooth
                data = bt.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.debug(f"BT -> Serial: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    # Write to serial
                    ser.write(data)
                    ser.flush()
            except Exception as e:
                if running:
                    log.error(f"Error in BT -> Serial relay: {e}")
                break
    except Exception as e:
        log.error(f"BT -> Serial thread error: {e}")
    finally:
        log.info("BT -> Serial relay thread stopped")

def serial_to_bt():
    """Relay data from Serial to Bluetooth"""
    global running, bt, ser
    log.info("Starting Serial -> BT relay thread")
    try:
        while running:
            try:
                # Read from serial
                data = ser.read(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.debug(f"Serial -> BT: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    # Write to Bluetooth
                    bt.send(data)
            except Exception as e:
                if running:
                    log.error(f"Error in Serial -> BT relay: {e}")
                break
    except Exception as e:
        log.error(f"Serial -> BT thread error: {e}")
    finally:
        log.info("Serial -> BT relay thread stopped")

# Start relay threads
bt_to_ser_thread = threading.Thread(target=bt_to_serial, daemon=True)
ser_to_bt_thread = threading.Thread(target=serial_to_bt, daemon=True)

bt_to_ser_thread.start()
ser_to_bt_thread.start()

log.info("Relay threads started")

# Main loop - monitor for exit conditions
try:
    while running:
        time.sleep(1)
        # Check if threads are still alive
        if not bt_to_ser_thread.is_alive() or not ser_to_bt_thread.is_alive():
            log.warning("One of the relay threads has stopped")
            running = False
            break
except KeyboardInterrupt:
    log.info("Keyboard interrupt received")
    running = False
except Exception as e:
    log.error(f"Error in main loop: {e}")
    running = False

# Cleanup
log.info("Shutting down...")
running = False
time.sleep(0.5)

try:
    bt.close()
except Exception:
    pass

try:
    server_sock.close()
except Exception:
    pass

log.info("Disconnected")
time.sleep(1)

log.info("Exiting eeboard.py")

