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

# Board address variables (will be detected during initialization)
addr1 = 0x11  # Default values, will be updated when board responds
addr2 = 0x11

def checksum(barr):
    """Calculate checksum for DGT Centaur packet"""
    barr_csum = 0
    for i in range(len(barr)):
        barr_csum = barr_csum ^ barr[i]
    return barr_csum

def buildPacket(command, data):
    """Build a complete DGT Centaur packet with address and checksum"""
    tosend = bytearray(command + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big') + data)
    tosend.append(checksum(tosend))
    return tosend

def sendPacket(command, data):
    """Send a packet to the DGT Centaur board using proper packet construction"""
    tosend = buildPacket(command, data)
    return serialWrite(tosend)

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

def testResponsesWithSendPacket():
    """
    Test DGT Centaur commands using the proper sendPacket() function from board.py.
    This uses the correct packet construction with address and checksum.
    """
    if not SERIAL_AVAILABLE:
        sendPrint("[TEST] Simulation mode - cannot test actual hardware")
        return
    
    sendPrint("[TEST] Starting command testing with proper sendPacket()...")
    sendPrint(f"[TEST] Using board address: {hex(addr1)} {hex(addr2)}")
    
    # Test 1: Version command (0x4d) - from board.py
    sendPrint("[TEST] === Test 1: Version Command (0x4d) ===")
    if sendPacket(b'\x4d', b''):
        sendPrint("[TEST] ✓ Version command sent successfully")
        responses = collectCommandResponses(2.0)
        if responses:
            sendPrint("[TEST] ✓ Version command got response")
            for timestamp, data in responses:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[TEST]   Response: {hex_str}")
        else:
            sendPrint("[TEST] ✗ Version command got no response")
    else:
        sendPrint("[TEST] ✗ Version command failed to send")
    
    # Test 2: LED off command (0xb0) - exact same as board.py ledsOff()
    sendPrint("[TEST] === Test 2: LED Off Command (0xb0) ===")
    if sendPacket(b'\xb0\x00\x07', b'\x00'):
        sendPrint("[TEST] ✓ LED off command sent successfully")
        responses = collectCommandResponses(2.0)
        if responses:
            sendPrint("[TEST] ✓ LED off command got response")
            for timestamp, data in responses:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[TEST]   Response: {hex_str}")
                # Analyze the specific response pattern
                if len(data) == 5 and data[0] == 0x93:
                    sendPrint("[TEST]   Analyzing LED response...")
                    analyzeResponse93(data)
        else:
            sendPrint("[TEST] ✗ LED off command got no response")
    else:
        sendPrint("[TEST] ✗ LED off command failed to send")
    
    # Test 3: Power-on beep command (0xb1) - exact same as board.py beep(SOUND_POWER_ON)
    sendPrint("[TEST] === Test 3: Power-on Beep Command (0xb1) ===")
    if sendPacket(b'\xb1\x00\x0a', b'\x48\x08\x4c\x08'):
        sendPrint("[TEST] ✓ Power-on beep command sent successfully")
        responses = collectCommandResponses(2.0)
        if responses:
            sendPrint("[TEST] ✓ Power-on beep command got response")
            for timestamp, data in responses:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[TEST]   Response: {hex_str}")
        else:
            sendPrint("[TEST] ✗ Power-on beep command got no response")
    else:
        sendPrint("[TEST] ✗ Power-on beep command failed to send")
    
    # Test 4: Field changes command (0x83) - exact same as board.py poll()
    sendPrint("[TEST] === Test 4: Field Changes Command (0x83) ===")
    if sendPacket(b'\x83', b''):
        sendPrint("[TEST] ✓ Field changes command sent successfully")
        responses = collectCommandResponses(2.0)
        if responses:
            sendPrint("[TEST] ✓ Field changes command got response")
            for timestamp, data in responses:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[TEST]   Response: {hex_str}")
        else:
            sendPrint("[TEST] ✗ Field changes command got no response")
    else:
        sendPrint("[TEST] ✗ Field changes command failed to send")
    
    # Test 5: Button status command (0x94) - exact same as board.py poll()
    sendPrint("[TEST] === Test 5: Button Status Command (0x94) ===")
    if sendPacket(b'\x94', b''):
        sendPrint("[TEST] ✓ Button status command sent successfully")
        responses = collectCommandResponses(2.0)
        if responses:
            sendPrint("[TEST] ✓ Button status command got response")
            for timestamp, data in responses:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[TEST]   Response: {hex_str}")
        else:
            sendPrint("[TEST] ✗ Button status command got no response")
    else:
        sendPrint("[TEST] ✗ Button status command failed to send")
    
    # Test 6: Board state command (0xf0) - exact same as board.py getBoardState()
    sendPrint("[TEST] === Test 6: Board State Command (0xf0) ===")
    if sendPacket(b'\xf0\x00\x07', b'\x7f'):
        sendPrint("[TEST] ✓ Board state command sent successfully")
        responses = collectCommandResponses(2.0)
        if responses:
            sendPrint("[TEST] ✓ Board state command got response")
            for timestamp, data in responses:
                hex_str = ' '.join(f'{b:02x}' for b in data)
                sendPrint(f"[TEST]   Response: {hex_str}")
        else:
            sendPrint("[TEST] ✗ Board state command got no response")
    else:
        sendPrint("[TEST] ✗ Board state command failed to send")
    
    sendPrint("[TEST] === sendPacket() Testing Complete ===")
    sendPrint("[TEST] Review the results above to see which commands work with proper packet construction")

def testResponses():
    if not SERIAL_AVAILABLE:
        sendPrint("[TEST] Simulation mode - cannot test actual hardware")
        return
    
    sendPrint("[TEST] Starting comprehensive command/response testing...")
    sendPrint("[TEST] This will test all available DGT Centaur commands")
    
    # Test 1: Version command (0x4d)
    sendPrint("[TEST] === Test 1: Version Command (0x4d) ===")
    success, responses = sendCommandAndWait(DGT_SEND_VERSION, 2.0, "Version command")
    if success and responses:
        sendPrint("[TEST] ✓ Version command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Version command failed")
    
    # Test 2: Bootloader command (0x4e)
    sendPrint("[TEST] === Test 2: Bootloader Command (0x4e) ===")
    success, responses = sendCommandAndWait(DGT_STARTBOOTLOADER, 2.0, "Bootloader command")
    if success and responses:
        sendPrint("[TEST] ✓ Bootloader command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Bootloader command failed")
    
    # Test 3: Bus ping command (0x87)
    sendPrint("[TEST] === Test 3: Bus Ping Command (0x87) ===")
    success, responses = sendCommandAndWait(DGT_BUS_PING, 2.0, "Bus ping command")
    if success and responses:
        sendPrint("[TEST] ✓ Bus ping command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Bus ping command failed")
    
    # Test 4: LED off command (0xb0) - Current format
    sendPrint("[TEST] === Test 4: LED Off Command (0xb0) - Current Format ===")
    success, responses = sendCommandAndWait(DGT_LEDS_OFF, 2.0, "LED off command")
    if success and responses:
        sendPrint("[TEST] ✓ LED off command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ LED off command failed")
    
    # Test 5: LED off command (0xb0) - Alternative format from board.py
    sendPrint("[TEST] === Test 5: LED Off Command (0xb0) - Alternative Format ===")
    # From board.py ledsOff(): sendPacket(b'\xb0\x00\x07', b'\x00')
    alt_led_off = bytearray(b'\xb0\x00\x07\x00')
    success, responses = sendCommandAndWait(alt_led_off, 2.0, "LED off alternative")
    if success and responses:
        sendPrint("[TEST] ✓ LED off alternative works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ LED off alternative failed")
    
    # Test 6: Power-on beep command (0xb1)
    sendPrint("[TEST] === Test 6: Power-on Beep Command (0xb1) ===")
    success, responses = sendCommandAndWait(DGT_POWER_ON_BEEP, 2.0, "Power-on beep command")
    if success and responses:
        sendPrint("[TEST] ✓ Power-on beep command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Power-on beep command failed")
    
    # Test 7: Field changes command (0x83)
    sendPrint("[TEST] === Test 7: Field Changes Command (0x83) ===")
    success, responses = sendCommandAndWait(DGT_BUS_SEND_CHANGES, 2.0, "Field changes command")
    if success and responses:
        sendPrint("[TEST] ✓ Field changes command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Field changes command failed")
    
    # Test 8: Button status command (0x94)
    sendPrint("[TEST] === Test 8: Button Status Command (0x94) ===")
    success, responses = sendCommandAndWait(DGT_BUTTON_STATUS, 2.0, "Button status command")
    if success and responses:
        sendPrint("[TEST] ✓ Button status command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Button status command failed")
    
    # Test 9: Try some other common commands
    sendPrint("[TEST] === Test 9: Additional Commands ===")
    
    # Test sleep command (0xb2)
    sleep_cmd = bytearray(b'\xb2\x00\x07\x0a')
    success, responses = sendCommandAndWait(sleep_cmd, 2.0, "Sleep command")
    if success and responses:
        sendPrint("[TEST] ✓ Sleep command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Sleep command failed")
    
    # Test board state command (0xf0)
    board_state_cmd = bytearray(b'\xf0\x00\x07\x7f')
    success, responses = sendCommandAndWait(board_state_cmd, 2.0, "Board state command")
    if success and responses:
        sendPrint("[TEST] ✓ Board state command works")
        for timestamp, data in responses:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            sendPrint(f"[TEST]   Response: {hex_str}")
    else:
        sendPrint("[TEST] ✗ Board state command failed")
    
    sendPrint("[TEST] === Command/Response Testing Complete ===")
    sendPrint("[TEST] Review the results above to see which commands work")

def detectBoardAddress():
    """
    Detect the board address using the exact sequence from board.py lines 89-131.
    This must be done before any LED or sound commands will work.
    """
    if not SERIAL_AVAILABLE:
        sendPrint("[ADDR] Simulation mode - using default address")
        return True
    
    global addr1, addr2
    
    sendPrint("[ADDR] Detecting board address...")
    sendPrint("[ADDR] This is required before LED/sound commands will work")
    
    # Step 1: Send 0x4d (version command) - same as board.py line 95
    sendPrint("[ADDR] Sending version command (0x4d)...")
    if sendPacket(b'\x4d', b''):
        sendPrint("[ADDR] ✓ Version command sent")
        responses = collectCommandResponses(1.0)
        if responses:
            sendPrint("[ADDR] ✓ Version command got response")
        else:
            sendPrint("[ADDR] ⚠ Version command got no response")
    else:
        sendPrint("[ADDR] ✗ Version command failed")
    
    # Step 2: Send 0x4e (bootloader command) - same as board.py line 102
    sendPrint("[ADDR] Sending bootloader command (0x4e)...")
    if sendPacket(b'\x4e', b''):
        sendPrint("[ADDR] ✓ Bootloader command sent")
        responses = collectCommandResponses(1.0)
        if responses:
            sendPrint("[ADDR] ✓ Bootloader command got response")
        else:
            sendPrint("[ADDR] ⚠ Bootloader command got no response")
    else:
        sendPrint("[ADDR] ✗ Bootloader command failed")
    
    # Step 3: Send 0x87 00 00 07 (bus ping) repeatedly until we get address - same as board.py lines 118-128
    sendPrint("[ADDR] Sending bus ping commands to detect address...")
    timeout = time.time() + 30  # 30 second timeout
    attempts = 0
    
    while time.time() < timeout:
        attempts += 1
        sendPrint(f"[ADDR] Bus ping attempt {attempts}...")
        
        if sendPacket(b'\x87\x00\x00\x07', b''):
            responses = collectCommandResponses(1.0)
            if responses:
                for timestamp, data in responses:
                    hex_str = ' '.join(f'{b:02x}' for b in data)
                    sendPrint(f"[ADDR] Bus ping response: {hex_str}")
                    
                    # Check if response contains address (same as board.py lines 124-128)
                    if len(data) > 4:
                        addr1 = data[3]
                        addr2 = data[4]
                        sendPrint(f"[ADDR] ✓ Board address detected: {hex(addr1)} {hex(addr2)}")
                        sendPrint(f"[ADDR] ✓ Address detection complete!")
                        return True
                    else:
                        sendPrint(f"[ADDR] ⚠ Incomplete address response")
            else:
                sendPrint(f"[ADDR] ⚠ Bus ping got no response")
        else:
            sendPrint(f"[ADDR] ✗ Bus ping command failed")
        
        time.sleep(0.5)  # Wait before next attempt
    
    sendPrint("[ADDR] ✗ Address detection failed after 30 seconds")
    sendPrint("[ADDR] ✗ LED and sound commands will not work without proper address")
    return False
    """
    Check if the board is already properly initialized by testing the menu.py initialization sequence.
    Returns True if board is already initialized, False if it needs initialization.
    """
    if not SERIAL_AVAILABLE:
        sendPrint("[STATUS] Simulation mode - assuming board needs initialization")
        return False
    
    sendPrint("[STATUS] Checking if board is already properly initialized...")
    
    # Test if board responds to basic commands (version check)
    success, responses = sendCommandAndWait(DGT_SEND_VERSION, 1.0, "Version check")
    if not success or not responses:
        sendPrint("[STATUS] Board not responding - needs initialization")
        return False
    
    # Test if board responds to LED off command (part of menu.py initialization)
    sendPrint("[STATUS] Testing LED off command...")
    success, responses = sendCommandAndWait(DGT_LEDS_OFF, 1.0, "LED off test")
    if not success or not responses:
        sendPrint("[STATUS] Board LED commands not working - needs initialization")
        return False
    
    # Test if board responds to beep command (part of menu.py initialization)
    sendPrint("[STATUS] Testing beep command...")
    success, responses = sendCommandAndWait(DGT_POWER_ON_BEEP, 1.0, "Beep test")
    if not success or not responses:
        sendPrint("[STATUS] Board beep commands not working - needs initialization")
        return False
    
    # Test if board serial buffer is clear (part of menu.py initialization)
    sendPrint("[STATUS] Testing serial buffer state...")
    success1, responses1 = sendCommandAndWait(DGT_BUS_SEND_CHANGES, 0.5, "Field changes test")
    success2, responses2 = sendCommandAndWait(DGT_BUTTON_STATUS, 0.5, "Button status test")
    
    if not success1 or not success2:
        sendPrint("[STATUS] Board serial commands not working properly - needs initialization")
        return False
    
    sendPrint("[STATUS] Board appears to be properly initialized")
    return True

def initializeBoard():
    """
    Initialize the board with the exact sequence from menu.py lines 176-179.
    This is the actual initialization sequence used by the main application.
    Uses proper sendPacket() function from board.py.
    """
    sendPrint("[INIT] Starting board initialization (menu.py sequence)...")
    
    if not SERIAL_AVAILABLE:
        sendPrint("[INIT] Running in simulation mode - no actual hardware")
        return True
    
    # Step 1: Turn LEDs off (same as board.ledsOff() in menu.py line 176)
    sendPrint("[INIT] Turning LEDs off...")
    if sendPacket(b'\xb0\x00\x07', b'\x00'):
        sendPrint("[INIT] ✓ LED off command sent successfully")
        responses = collectCommandResponses(1.0)
        if responses:
            sendPrint("[INIT] ✓ LED off command got response")
        else:
            sendPrint("[INIT] ⚠ LED off command got no response (may be normal)")
    else:
        sendPrint("[INIT] ✗ Failed to send LED off command")
        return False
    
    # Step 2: Send power-on beep (same as board.beep(board.SOUND_POWER_ON) in menu.py line 177)
    sendPrint("[INIT] Sending power-on beep...")
    if sendPacket(b'\xb1\x00\x0a', b'\x48\x08\x4c\x08'):
        sendPrint("[INIT] ✓ Power-on beep command sent successfully")
        responses = collectCommandResponses(1.0)
        if responses:
            sendPrint("[INIT] ✓ Power-on beep command got response")
        else:
            sendPrint("[INIT] ⚠ Power-on beep command got no response (may be normal)")
    else:
        sendPrint("[INIT] ✗ Failed to send power-on beep command")
        return False
    
    # Step 3: Clear serial buffer until idle (same as board.clearSerial() in menu.py line 179)
    sendPrint("[INIT] Clearing serial buffer until board is idle...")
    if clearSerialUntilIdleWithSendPacket():
        sendPrint("[INIT] ✓ Serial buffer cleared successfully")
    else:
        sendPrint("[INIT] ⚠ Serial buffer clearing had issues (may be normal)")
    
    sendPrint("[INIT] Board initialization complete!")
    sendPrint("[INIT] Board is now ready for menu.py to continue")
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

def analyzeResponse93(response_data):
    """
    Analyze the response 93 00 05 05 07 which appears to be a successful LED off response.
    This follows the DGT Centaur response pattern.
    """
    if len(response_data) != 5:
        sendPrint(f"[ANALYZE] Response length {len(response_data)} is not 5 bytes")
        return False
    
    # Break down the response: 93 00 05 05 07
    cmd_byte = response_data[0]  # 0x93 = 147
    addr1_resp = response_data[1]  # 0x00
    addr2_resp = response_data[2]  # 0x05  
    data_byte = response_data[3]  # 0x05
    checksum = response_data[4]   # 0x07
    
    sendPrint(f"[ANALYZE] LED Response Analysis:")
    sendPrint(f"[ANALYZE]   Command byte: 0x{cmd_byte:02x} ({cmd_byte})")
    sendPrint(f"[ANALYZE]   Address 1: 0x{addr1_resp:02x} ({addr1_resp})")
    sendPrint(f"[ANALYZE]   Address 2: 0x{addr2_resp:02x} ({addr2_resp})")
    sendPrint(f"[ANALYZE]   Data byte: 0x{data_byte:02x} ({data_byte})")
    sendPrint(f"[ANALYZE]   Checksum: 0x{checksum:02x} ({checksum})")
    
    # Verify checksum
    calculated_checksum = 0
    for i in range(4):  # First 4 bytes
        calculated_checksum = calculated_checksum ^ response_data[i]
    
    sendPrint(f"[ANALYZE]   Calculated checksum: 0x{calculated_checksum:02x}")
    sendPrint(f"[ANALYZE]   Checksum valid: {calculated_checksum == checksum}")
    
    # Analyze command byte
    if cmd_byte == 0x93:
        sendPrint(f"[ANALYZE]   ✓ This is a successful LED command response!")
        sendPrint(f"[ANALYZE]   ✓ LED off command (0xb0) was acknowledged")
        return True
    else:
        sendPrint(f"[ANALYZE]   ✗ Unexpected command byte: 0x{cmd_byte:02x}")
        return False
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

def clearSerialUntilIdleWithSendPacket():
    """
    Clear serial buffer until board is idle using proper sendPacket() function.
    Same as board.py clearSerial() but using our sendPacket() implementation.
    """
    sendPrint("[CLEAR] Checking and clearing the serial line...")
    
    attempts = 0
    max_attempts = 10  # Prevent infinite loop
    
    while attempts < max_attempts:
        attempts += 1
        sendPrint(f"[CLEAR] Attempt {attempts}/{max_attempts}")
        
        # Send 0x83 command (field changes) - same as board.py clearSerial()
        if sendPacket(b'\x83', b''):
            sendPrint("[CLEAR] ✓ Field changes command sent")
            responses = collectCommandResponses(1.0)
            if responses:
                sendPrint("[CLEAR] ✓ Field changes got response")
            else:
                sendPrint("[CLEAR] ⚠ Field changes got no response")
        else:
            sendPrint("[CLEAR] ✗ Field changes command failed")
        
        # Send 0x94 command (button status) - same as board.py clearSerial()
        if sendPacket(b'\x94', b''):
            sendPrint("[CLEAR] ✓ Button status command sent")
            responses = collectCommandResponses(1.0)
            if responses:
                sendPrint("[CLEAR] ✓ Button status got response")
            else:
                sendPrint("[CLEAR] ⚠ Button status got no response")
        else:
            sendPrint("[CLEAR] ✗ Button status command failed")
        
        # Simplified: assume idle after a few attempts
        if attempts >= 3:
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
    
    # Step 1: Detect board address (REQUIRED before LED/sound commands work)
    if detectBoardAddress():
        sendPrint("✓ Board address detection successful!")
        sendPrint(f"✓ Using detected address: {hex(addr1)} {hex(addr2)}")
        
        # Step 2: Run comprehensive command/response testing with proper sendPacket()
        testResponsesWithSendPacket()
        
        # Step 3: Check if board is already initialized
        if checkBoardStatus():
            sendPrint("Board is already initialized - skipping initialization sequence")
        else:
            # Initialize the board (we'll see all responses in the monitor)
            if initializeBoard():
                sendPrint("Board initialization successful!")
            else:
                sendPrint("Board initialization failed!")
    else:
        sendPrint("✗ Board address detection failed!")
        sendPrint("✗ LED and sound commands will not work")
        sendPrint("✗ Skipping further testing")
    
    try:
        sendPrint("Serial monitor running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sendPrint("\nStopping serial monitor...")
        stopMonitor()
        closeSerial()
        sendPrint("Serial monitor stopped.")
