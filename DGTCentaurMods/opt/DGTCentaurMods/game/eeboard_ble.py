# Proxy/Relay between Bluetooth Low Energy (BLE) and Hardware Serial
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
import os
import psutil
import dbus
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController
from DGTCentaurMods.board.settings import Settings
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic
from DGTCentaurMods.thirdparty.bletools import BleTools

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

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
log.info("Waiting for BLE connection...")

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

# Relay state
running = True
ble_connected = False

class UARTAdvertisement(Advertisement):
    """BLE advertisement for UART service - compatible with iOS, macOS, and Android"""
    def __init__(self, index):
        Advertisement.__init__(self, index, "peripheral")
        # Shorter name for better iOS/macOS compatibility
        self.add_local_name("DGT Centaur BLE")
        self.include_tx_power = True
        self.add_service_uuid("5f040001-5866-11ec-bf63-0242ac130002")
    
    def register_ad_callback(self):
        """Callback when advertisement is successfully registered"""
        log.info("BLE advertisement registered successfully (iOS/macOS/Android compatible)")
    
    def register_ad_error_callback(self, error):
        """Callback when advertisement registration fails"""
        log.error(f"Failed to register BLE advertisement: {error}")
    
    def register(self):
        """Register advertisement with iOS/macOS compatible options"""
        bus = BleTools.get_bus()
        adapter = BleTools.find_adapter(bus)
        
        ad_manager = dbus.Interface(
            bus.get_object("org.bluez", adapter),
            "org.bluez.LEAdvertisingManager1")
        
        # iOS/macOS compatibility options:
        # - MinInterval: 20ms (0x0014) - iOS recommended starting interval
        # - MaxInterval: 152.5ms (0x0098) - iOS compatible interval
        # These intervals improve discoverability on iOS/macOS devices
        options = {
            "MinInterval": dbus.UInt16(0x0014),  # 20ms
            "MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
        }
        
        log.info("Registering BLE advertisement with iOS/macOS compatible intervals (20ms-152.5ms)")
        ad_manager.RegisterAdvertisement(
            self.get_path(),
            options,
            reply_handler=self.register_ad_callback,
            error_handler=self.register_ad_error_callback)

class UARTService(Service):
    """BLE UART service for relaying data between BLE and serial"""
    tx_obj = None

    UART_SVC_UUID = "5f040001-5866-11ec-bf63-0242ac130002"

    def __init__(self, index):
        Service.__init__(self, index, self.UART_SVC_UUID, True)
        self.add_characteristic(UARTTXCharacteristic(self))
        self.add_characteristic(UARTRXCharacteristic(self))

class UARTRXCharacteristic(Characteristic):
    """BLE RX characteristic - receives data from BLE client and writes to serial"""
    UARTRX_CHARACTERISTIC_UUID = "5f040002-5866-11ec-bf63-0242ac130002"

    def __init__(self, service):
        Characteristic.__init__(
                self, self.UARTRX_CHARACTERISTIC_UUID,
                ["write"], service)

    def WriteValue(self, value, options):
        """When the remote device writes data via BLE, relay it to serial"""
        global running, ser, ble_connected
        if not running:
            return
        
        ble_connected = True
        log.info("Received message from BLE: " + str(value))
        bytes = bytearray()
        for i in range(0, len(value)):
            bytes.append(value[i])
        
        log.debug(f"BLE -> Serial: {' '.join(f'{b:02x}' for b in bytes)}")
        
        try:
            # Write to serial
            ser.write(bytes)
            ser.flush()
        except Exception as e:
            log.error(f"Error writing to serial from BLE: {e}")

class UARTTXCharacteristic(Characteristic):
    """BLE TX characteristic - sends data from serial to BLE client"""
    UARTTX_CHARACTERISTIC_UUID = "5f040003-5866-11ec-bf63-0242ac130002"

    def __init__(self, service):
        Characteristic.__init__(
                self, self.UARTTX_CHARACTERISTIC_UUID,
                ["read", "notify"], service)
        self.notifying = False

    def sendMessage(self, data):
        """Send a message via BLE notification"""
        if not self.notifying:
            return
        log.debug(f"Serial -> BLE: {' '.join(f'{b:02x}' for b in data)}")
        tosend = bytearray()
        for x in range(0, len(data)):
            tosend.append(data[x])
        UARTService.tx_obj.updateValue(tosend)

    def StartNotify(self):
        """Called when BLE client subscribes to notifications"""
        log.info("BLE client started notifications")
        UARTService.tx_obj = self
        self.notifying = True
        global ble_connected
        ble_connected = True
        return self.notifying

    def StopNotify(self):
        """Called when BLE client unsubscribes from notifications"""
        if not self.notifying:
            return
        log.info("BLE client stopped notifications")
        self.notifying = False
        global ble_connected
        ble_connected = False
        return self.notifying

    def updateValue(self, value):
        """Update the characteristic value and notify subscribers"""
        if not self.notifying:
            return
        send = dbus.Array(signature=dbus.Signature('y'))
        for i in range(0, len(value)):
            send.append(dbus.Byte(value[i]))
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': send}, [])

    def ReadValue(self, options):
        """Read the current characteristic value"""
        value = bytearray()
        value.append(0)
        return value

def serial_to_ble():
    """Relay data from Serial to BLE"""
    global running, ser
    log.info("Starting Serial -> BLE relay thread")
    try:
        while running:
            try:
                # Read from serial
                data = ser.read(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.debug(f"Serial -> BLE: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    # Write to BLE via TX characteristic
                    if UARTService.tx_obj is not None:
                        UARTService.tx_obj.sendMessage(data_bytes)
            except Exception as e:
                if running:
                    log.error(f"Error in Serial -> BLE relay: {e}")
                break
    except Exception as e:
        log.error(f"Serial -> BLE thread error: {e}")
    finally:
        log.info("Serial -> BLE relay thread stopped")

# Initialize BLE application
app = Application()
app.add_service(UARTService(0))
app.register()

adv = UARTAdvertisement(0)
adv.register()

log.info("BLE service registered and advertising")
log.info("Waiting for BLE connection...")

# Start serial to BLE relay thread
ser_to_ble_thread = threading.Thread(target=serial_to_ble, daemon=True)
ser_to_ble_thread.start()

log.info("Relay thread started")

# Main loop - run BLE application mainloop
try:
    app.run()
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
    app.quit()
except Exception:
    pass

log.info("Disconnected")
time.sleep(1)

log.info("Exiting eeboard_ble.py")

