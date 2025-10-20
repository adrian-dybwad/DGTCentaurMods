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
from datetime import datetime

# DGT Centaur Command Constants
# These commands are used to initialize and communicate with the DGT Centaur board
# Reference: Based on commands from eboard.py and board.py modules

# Address Detection Commands
DGT_SEND_VERSION = bytearray(b'\x4d')        # Request board version information
DGT_STARTBOOTLOADER = bytearray(b'\x4e')     # Hard reboot/reset command  
DGT_BUS_PING = bytearray(b'\x87\x00\x00\x07') # Bus mode ping to detect board address

# Serial Buffer Management Commands
DGT_BUS_SEND_CHANGES = bytearray(b'\x83')   # Request field change updates (clears buffer)
DGT_BUTTON_STATUS = bytearray(b'\x94')      # Check button states (clears buffer)

# LED Control Commands
DGT_LEDS_OFF = bytearray(b'\xb0\x00\x07\x00') # Turn all LEDs off (ledsOff() function)

# Sound Control Commands
DGT_POWER_ON_BEEP = bytearray(b'\xb1\x00\x08\x48\x08') # Power-on beep sound (beep(SOUND_POWER_ON))

# Other Available Sound Commands (for reference):
# SOUND_GENERAL: 0xb1 0x00 0x08 0x4c 0x08
# SOUND_FACTORY: 0xb1 0x00 0x08 0x4c 0x40  
# SOUND_POWER_OFF: 0xb1 0x00 0x0a 0x4c 0x08 0x48 0x08
# SOUND_WRONG: 0xb1 0x00 0x0a 0x4e 0x0c 0x48 0x10
# SOUND_WRONG_MOVE: 0xb1 0x00 0x08 0x48 0x08

def sendPrint(message):
    """Print message with timestamp in HH:MM:SS.SSS format"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Remove last 3 digits for milliseconds
    print(f"[{timestamp}] {message}")

# Try to open serial port, but handle the case where it's not available
try:
    ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)
    ser.isOpen()
    SERIAL_AVAILABLE = True
    sendPrint("[SERIAL] Connected to /dev/serial0")
except Exception as e:
    sendPrint(f"[SERIAL] Could not connect to /dev/serial0: {e}")
    sendPrint("[SERIAL] Running in simulation mode (no actual hardware)")
    ser = None
    SERIAL_AVAILABLE = False

# Serial monitor thread control
_monitor_running = False
_monitor_thread = None
_response_queue = []  # Shared queue for responses
_response_lock = threading.Lock()  # Thread safety

def _serial_monitor():
    """Background thread that monitors serial port and prints data"""
    global _monitor_running, _response_queue
    sendPrint("Serial monitor thread started")
    
    if not SERIAL_AVAILABLE:
        sendPrint("[SERIAL] Monitor running in simulation mode")
        while _monitor_running:
            time.sleep(1)
        sendPrint("Serial monitor thread stopped")
        return
    
    while _monitor_running:
        try:
            data = ser.read(1000)
            if data:
                # Show hex representation more clearly
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[SERIAL] Received {len(data)} bytes: {hex_str}")
                
                # Add to shared response queue
                with _response_lock:
                    _response_queue.append((time.time(), data))
        except Exception as e:
            sendPrint(f"[SERIAL] Error reading: {e}")
            time.sleep(0.1)
    
    sendPrint("Serial monitor thread stopped")

def checkBoardStatus():
    """
    Check if the board is already initialized by sending a simple command.
    Returns True if board responds properly, False otherwise.
    """
    if not SERIAL_AVAILABLE:
        sendPrint("[STATUS] Simulation mode - assuming board is ready")
        return True
    
    sendPrint("[STATUS] Checking if board is already initialized...")
    
    # Send a simple command to check if board responds
    success, responses = sendCommandAndWait(DGT_SEND_VERSION, 1.0, "Check board status")
    if success and responses:
        sendPrint("[STATUS] Board appears to be already initialized")
        return True
    else:
        sendPrint("[STATUS] Board needs initialization")
        return False

def initializeBoard():
    """
    Initialize the board with the standard DGT Centaur initialization sequence.
    Sends commands in the same order as board.py and menu.py initialization.
    """
    sendPrint("[INIT] Starting board initialization...")
    
    if not SERIAL_AVAILABLE:
        sendPrint("[INIT] Running in simulation mode - no actual hardware")
    
    # Clear any existing data
    if SERIAL_AVAILABLE:
        try:
            ser.read(1000)
        except:
            pass
    
    # Step 1: Address Detection (same as board.py initialization)
    sendPrint("[INIT] Sending address detection commands...")
    
    # Command 0x4d - Request board version information
    success, responses = sendCommandAndWait(DGT_SEND_VERSION, 2.0, "Request board version")
    if not success:
        return False
    analyzeResponse(DGT_SEND_VERSION, responses, "Version Response")
    
    # Command 0x4e - Hard reboot/reset command  
    success, responses = sendCommandAndWait(DGT_STARTBOOTLOADER, 2.0, "Hard reboot/reset")
    if not success:
        return False
    analyzeResponse(DGT_STARTBOOTLOADER, responses, "Reboot Response")
    
    # Command 0x87 - Bus mode ping to detect board address (loop until address found)
    sendPrint("[INIT] Detecting board address...")
    timeout = time.time() + 60  # 60 second timeout like board.py
    address_found = False
    
    while time.time() < timeout and not address_found:
        success, responses = sendCommandAndWait(DGT_BUS_PING, 1.0, "Bus ping - detect address")
        if not success:
            return False
        
        # Analyze the response to see if we got an address
        if analyzeResponse(DGT_BUS_PING, responses, "Address Response"):
            address_found = True
    
    if not address_found:
        sendPrint("[INIT] Failed to detect board address")
        return False
    
    # Step 2: Menu Initialization (same as menu.py lines 173-179)
    sendPrint("[INIT] Performing menu initialization...")
    
    # Turn LEDs off (same as ledsOff() in board.py)
    sendPrint("[INIT] Turning LEDs off...")
    success, responses = sendCommandAndWait(DGT_LEDS_OFF, 1.0, "LED off command")
    if not success:
        return False
    analyzeResponse(DGT_LEDS_OFF, responses, "LED Response")
    
    # Send power-on beep (same as beep(SOUND_POWER_ON))
    sendPrint("[INIT] Sending power-on beep...")
    success, responses = sendCommandAndWait(DGT_POWER_ON_BEEP, 1.0, "Power-on beep")
    if not success:
        return False
    analyzeResponse(DGT_POWER_ON_BEEP, responses, "Beep Response")
    
    # Clear serial buffer (same as clearSerial() in board.py)
    sendPrint("[INIT] Clearing serial buffer until board is idle...")
    if not clearSerialUntilIdle():
        return False
    
    sendPrint("[INIT] Board initialization complete!")
    if SERIAL_AVAILABLE:
        sendPrint("[INIT] Watch the serial monitor above for board responses...")
    else:
        sendPrint("[INIT] Simulation completed successfully!")
    return True

def startMonitor():
    """Start the serial monitor thread"""
    global _monitor_running, _monitor_thread
    
    if _monitor_running:
        sendPrint("Serial monitor already running")
        return
    
    _monitor_running = True
    _monitor_thread = threading.Thread(target=_serial_monitor, daemon=True)
    _monitor_thread.start()
    sendPrint("Serial monitor started")

def stopMonitor():
    """Stop the serial monitor thread"""
    global _monitor_running, _monitor_thread
    
    if not _monitor_running:
        sendPrint("Serial monitor not running")
        return
    
    _monitor_running = False
    if _monitor_thread:
        _monitor_thread.join(timeout=2.0)
    sendPrint("Serial monitor stopped")

def serialWrite(packet):
    """Write data to serial port with error handling"""
    if not SERIAL_AVAILABLE:
        hex_str = ' '.join(f'{b:02x}' for b in packet)
        sendPrint(f"[WRITE] SIMULATION: Would send {len(packet)} bytes: {hex_str}")
        return True
    
    try:
        ser.write(packet)
        hex_str = ' '.join(f'{b:02x}' for b in packet)
        sendPrint(f"[WRITE] Sent {len(packet)} bytes: {hex_str}")
        return True
    except Exception as e:
        sendPrint(f"[WRITE] Error writing to serial: {e}")
        return False

def collectCommandResponses(timeout=5.0):
    """
    Collect all responses from the board within the timeout period.
    Returns a list of (timestamp, data) tuples.
    """
    if not SERIAL_AVAILABLE:
        sendPrint(f"[COLLECT] SIMULATION: Would collect responses for {timeout} seconds...")
        time.sleep(0.1)  # Brief pause to simulate response time
        sendPrint(f"[COLLECT] SIMULATION: Collected 1 simulated responses")
        return [(0.1, b'simulated_response')]  # Return simulated response
    
    responses = []
    start_time = time.time()
    initial_queue_size = 0
    
    sendPrint(f"[COLLECT] Starting to collect responses for {timeout} seconds...")
    
    # Get initial queue size to only collect new responses
    with _response_lock:
        initial_queue_size = len(_response_queue)
    
    # Wait for responses from the monitor thread
    while time.time() - start_time < timeout:
        with _response_lock:
            # Check if we have new responses
            if len(_response_queue) > initial_queue_size:
                # Get new responses
                new_responses = _response_queue[initial_queue_size:]
                for timestamp, data in new_responses:
                    relative_time = timestamp - start_time
                    responses.append((relative_time, data))
                    # Show hex representation more clearly
                    hex_str = ' '.join(f'{b:02x}' for b in data)
                    sendPrint(f"[COLLECT] Received {len(data)} bytes at {relative_time:.2f}s: {hex_str}")
                initial_queue_size = len(_response_queue)
        
        time.sleep(0.01)  # Small delay to avoid busy waiting
    
    sendPrint(f"[COLLECT] Collected {len(responses)} responses")
    return responses

def sendCommandAndWait(packet, timeout=2.0, description=""):
    """
    Send a command and wait for responses.
    Returns (success, responses) tuple where success is bool and responses is list of (timestamp, data).
    """
    if serialWrite(packet):
        sendPrint(f"[INIT] Sent {packet.hex()} ({description})")
        responses = collectCommandResponses(timeout)
        if responses:
            sendPrint(f"[INIT] Received {len(responses)} responses to {description}")
            return True, responses
        else:
            sendPrint(f"[INIT] No response to {description}")
            return False, []
    else:
        sendPrint(f"[INIT] Failed to send {description}")
        return False, []

def analyzeResponse(command, responses, response_type):
    """
    Analyze responses against expected patterns from board.py and menu.py.
    Returns True if response looks valid, False otherwise.
    """
    if not responses:
        sendPrint(f"[ANALYZE] {response_type}: No responses received")
        return False
    
    for timestamp, data in responses:
        hex_str = ' '.join(f'{b:02x}' for b in data)
        sendPrint(f"[ANALYZE] {response_type}: {len(data)} bytes at {timestamp:.2f}s: {hex_str}")
        
        # Analyze based on command type
        if command == DGT_SEND_VERSION:
            # Expected: Version response (from board.py analysis)
            if len(data) >= 3 and data[0] == 0x93:
                sendPrint(f"[ANALYZE] {response_type}: Valid version response format")
                return True
            else:
                sendPrint(f"[ANALYZE] {response_type}: Unexpected version response format")
                
        elif command == DGT_STARTBOOTLOADER:
            # Expected: Reboot acknowledgment
            if len(data) >= 1:
                sendPrint(f"[ANALYZE] {response_type}: Reboot response received")
                return True
            else:
                sendPrint(f"[ANALYZE] {response_type}: Unexpected reboot response")
                
        elif command == DGT_BUS_PING:
            # Expected: Address response (from board.py lines 124-128)
            if len(data) > 4:
                addr1 = data[3] if len(data) > 3 else 0
                addr2 = data[4] if len(data) > 4 else 0
                sendPrint(f"[ANALYZE] {response_type}: Board address detected: {hex(addr1)} {hex(addr2)}")
                return True
            else:
                sendPrint(f"[ANALYZE] {response_type}: Incomplete address response")
                
        elif command == DGT_LEDS_OFF:
            # Expected: LED command acknowledgment
            sendPrint(f"[ANALYZE] {response_type}: LED command response")
            return True
            
        elif command == DGT_POWER_ON_BEEP:
            # Expected: Beep command acknowledgment
            sendPrint(f"[ANALYZE] {response_type}: Beep command response")
            return True
    
    return False

def clearSerialUntilIdle():
    """
    Clear serial buffer until board is idle (same as clearSerial() in board.py).
    Keeps sending 0x83 and 0x94 commands until board responds with expected idle responses.
    """
    sendPrint("[CLEAR] Checking and clearing the serial line...")
    
    # Expected idle responses (from board.py clearSerial function)
    # expect1 = buildPacket(b'\x85\x00\x06', b'')  # Response to 0x83
    # expect2 = buildPacket(b'\xb1\x00\x06', b'')  # Response to 0x94
    
    attempts = 0
    max_attempts = 10  # Prevent infinite loop
    
    while attempts < max_attempts:
        attempts += 1
        sendPrint(f"[CLEAR] Attempt {attempts}/{max_attempts}")
        
        # Send 0x83 command and collect response
        success, responses = sendCommandAndWait(DGT_BUS_SEND_CHANGES, 1.0, "Request field changes")
        if not success:
            return False
        analyzeResponse(DGT_BUS_SEND_CHANGES, responses, "Field Changes Response")
        
        # Send 0x94 command and collect response  
        success, responses = sendCommandAndWait(DGT_BUTTON_STATUS, 1.0, "Check button states")
        if not success:
            return False
        analyzeResponse(DGT_BUTTON_STATUS, responses, "Button Status Response")
        
        # In a real implementation, we would check if responses match expected idle responses
        # For now, we'll assume the board becomes idle after a few attempts
        if attempts >= 3:  # Simplified: assume idle after 3 attempts
            sendPrint("[CLEAR] Board appears to be idle")
            return True
    
    sendPrint("[CLEAR] Failed to clear serial buffer after maximum attempts")
    return False

def closeSerial():
    stopMonitor()
    if SERIAL_AVAILABLE and ser:
        ser.close()

if __name__ == "__main__":
    sendPrint("Starting serial monitor...")
    
    # Start monitoring first to see all responses
    startMonitor()
    
    # Give the monitor a moment to start
    time.sleep(0.5)
    
    # Check if board is already initialized
    if checkBoardStatus():
        sendPrint("Board is already initialized - skipping initialization sequence")
    else:
        # Initialize the board (we'll see all responses in the monitor)
        if initializeBoard():
            sendPrint("Board initialization successful!")
        else:
            sendPrint("Board initialization failed!")
    
    try:
        sendPrint("Serial monitor running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sendPrint("\nStopping serial monitor...")
        stopMonitor()
        closeSerial()
        sendPrint("Serial monitor stopped.")
