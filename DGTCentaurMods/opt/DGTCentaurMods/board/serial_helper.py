# DGT Centaur board control functions
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
# ( https://github.com/adrian-dybwad/DGTCentaur )
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
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import serial
import threading
import time

ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)
ser.isOpen()

# Serial monitor thread control
_monitor_running = False
_monitor_thread = None

def _serial_monitor():
    """Background thread that monitors serial port and prints data"""
    global _monitor_running
    print("Serial monitor thread started")
    
    while _monitor_running:
        try:
            data = ser.read(1000)
            if data:
                print(f"[SERIAL] Received {len(data)} bytes: {data.hex()}")
        except Exception as e:
            print(f"[SERIAL] Error reading: {e}")
            time.sleep(0.1)
    
    print("Serial monitor thread stopped")

def start_monitor():
    """Start the serial monitor thread"""
    global _monitor_running, _monitor_thread
    
    if _monitor_running:
        print("Serial monitor already running")
        return
    
    _monitor_running = True
    _monitor_thread = threading.Thread(target=_serial_monitor, daemon=True)
    _monitor_thread.start()
    print("Serial monitor started")

def stop_monitor():
    """Stop the serial monitor thread"""
    global _monitor_running, _monitor_thread
    
    if not _monitor_running:
        print("Serial monitor not running")
        return
    
    _monitor_running = False
    if _monitor_thread:
        _monitor_thread.join(timeout=2.0)
    print("Serial monitor stopped")

def sendPacket(packet):
    ser.write(packet)

def closeSerial():
    stop_monitor()
    ser.close()

start_monitor()
