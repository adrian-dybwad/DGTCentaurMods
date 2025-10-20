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

# Timeout checking thread
_timeout_thread = None
_timeout_running = False

# Async State Machine for Command/Response Handling
class CommandState:
    PENDING = "pending"      # Command sent, waiting for response
    COMPLETED = "completed"  # Response received, callback called
    TIMEOUT = "timeout"      # No response within timeout
    FAILED = "failed"        # Command failed to send

class CommandRequest:
    def __init__(self, command_id, command, callback, timeout, description):
        self.command_id = command_id
        self.command = command
        self.callback = callback
        self.timeout = timeout
        self.description = description
        self.state = CommandState.PENDING
        self.sent_time = time.time()
        self.responses = []

# State machine storage
_command_requests = {}  # {command_id: CommandRequest}
_command_counter = 0
_command_lock = threading.Lock()

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

def serialWrite(data):
    """Write data to serial port with error handling"""
    if not SERIAL_AVAILABLE or ser is None:
        sendPrint(f"[WRITE] Simulation mode - would send {len(data)} bytes: {data.hex()}")
        return True
    
    try:
        ser.write(data)
        hex_str = ' '.join(f'{b:02x}' for b in data)
        sendPrint(f"[WRITE] Sent {len(data)} bytes: {hex_str}")
        return True
    except Exception as e:
        sendPrint(f"[WRITE] Error writing to serial: {e}")
        return False

def sendCommand(command, callback=None, timeout=2.0, description=""):
    """
    STATE MACHINE: Send command and transition to PENDING state
    
    Flow:
    1. Create CommandRequest object
    2. Try to send command (raw write for address detection, packet for others)
    3. If successful: transition to PENDING state
    4. If failed: transition to FAILED state
    5. Return command_id for tracking
    """
    global _command_counter
    
    sendPrint(f"[SEND] sendCommand called: {description}")
    
    if not SERIAL_AVAILABLE:
        sendPrint(f"[SEND] Simulation mode - would send command {command.hex()}")
        if callback:
            callback(True, [], description)
        return 0
    
    # Create command request object
    sendPrint(f"[SEND] About to acquire _command_lock")
    with _command_lock:
        sendPrint(f"[SEND] Acquired _command_lock")
        _command_counter += 1
        command_id = _command_counter
        sendPrint(f"[SEND] Updated command_id to {command_id}")
    
    sendPrint(f"[SEND] Released _command_lock for command ID {command_id}")
    
    request = CommandRequest(command_id, command, callback, timeout, description)
    
    # Determine if this is a raw write (for address detection) or packet write
    is_raw_write = "(RAW)" in description
    
    sendPrint(f"[SEND] Command ID {command_id}: {description} (raw={is_raw_write})")
    
    # Try to send command
    if is_raw_write:
        # Raw write for address detection commands
        success = serialWrite(command)
        sendPrint(f"[SEND] Raw write result: {success}")
    else:
        # Packet write for normal commands
        success = sendPacket(command, b'')
        sendPrint(f"[SEND] Packet write result: {success}")
    
    if not success:
        # Transition to FAILED state
        request.state = CommandState.FAILED
        sendPrint(f"[SEND] ✗ {description} FAILED to send")
        if callback:
            callback(False, [], description)
        return command_id
    
    # Transition to PENDING state
    request.state = CommandState.PENDING
    with _command_lock:
        _command_requests[command_id] = request
    
    sendPrint(f"[SEND] → {description} PENDING (ID: {command_id})")
    return command_id

def _transitionToCompleted(command_id, response_data):
    """
    STATE MACHINE: Transition command from PENDING to COMPLETED
    
    Flow:
    1. Find command request
    2. Add response data
    3. Transition to COMPLETED state
    4. Call callback
    5. Remove from pending requests
    """
    callback_to_call = None
    callback_args = None
    
    with _command_lock:
        if command_id not in _command_requests:
            sendPrint(f"[TRANSITION] Command ID {command_id} not found in requests")
            return
        
        request = _command_requests[command_id]
        
        # Transition to COMPLETED state
        request.state = CommandState.COMPLETED
        request.responses.append((time.time(), response_data))
        
        sendPrint(f"[TRANSITION] → {request.description} COMPLETED")
        
        # Prepare callback to be called outside the lock
        if request.callback:
            hex_str = ' '.join(f'{b:02x}' for b in response_data)
            sendPrint(f"[TRANSITION]   Response: {hex_str}")
            sendPrint(f"[TRANSITION]   Preparing callback for: {request.description}")
            callback_to_call = request.callback
            callback_args = (True, request.responses, request.description)
        else:
            sendPrint(f"[TRANSITION]   No callback registered for: {request.description}")
        
        # Remove from pending requests
        del _command_requests[command_id]
    
    # Call callback outside the lock to avoid deadlock
    if callback_to_call:
        sendPrint(f"[TRANSITION]   Calling callback for: {request.description}")
        try:
            callback_to_call(*callback_args)
        except Exception as e:
            sendPrint(f"[TRANSITION]   ERROR in callback: {e}")
            import traceback
            traceback.print_exc()

def _transitionToTimeout(command_id):
    """
    STATE MACHINE: Transition command from PENDING to TIMEOUT
    
    Flow:
    1. Find command request
    2. Transition to TIMEOUT state
    3. Call callback with failure
    4. Remove from pending requests
    """
    callback_to_call = None
    callback_args = None
    
    with _command_lock:
        if command_id not in _command_requests:
            return
        
        request = _command_requests[command_id]
        
        # Transition to TIMEOUT state
        request.state = CommandState.TIMEOUT
        
        sendPrint(f"[STATE] → {request.description} TIMEOUT")
        
        # Prepare callback to be called outside the lock
        if request.callback:
            sendPrint(f"[TRANSITION]   Preparing timeout callback for: {request.description}")
            callback_to_call = request.callback
            callback_args = (False, [], request.description)
        else:
            sendPrint(f"[TRANSITION]   No callback registered for timeout: {request.description}")
        
        # Remove from pending requests
        del _command_requests[command_id]
    
    # Call callback outside the lock to avoid deadlock
    if callback_to_call:
        sendPrint(f"[TRANSITION]   Calling timeout callback for: {request.description}")
        try:
            callback_to_call(*callback_args)
        except Exception as e:
            sendPrint(f"[TRANSITION]   ERROR in timeout callback: {e}")
            import traceback
            traceback.print_exc()

def _processResponse(data):
    """
    STATE MACHINE: Process incoming response and trigger state transitions
    
    Flow:
    1. Find first PENDING command (simple matching for now)
    2. Transition it to COMPLETED state
    3. Clean up any timed out commands
    """
    hex_str = ' '.join(f'{b:02x}' for b in data)
    sendPrint(f"[PROCESS] Processing response: {hex_str}")
    
    # Decide actions while holding the lock, but perform transitions after releasing it
    to_complete = None
    to_timeout = []

    with _command_lock:
        # Debug: Show all pending commands
        pending_count = sum(1 for req in _command_requests.values() if req.state == CommandState.PENDING)
        sendPrint(f"[PROCESS] Found {pending_count} pending commands")
        
        # Find first PENDING command to match this response
        for command_id, request in _command_requests.items():
            if request.state == CommandState.PENDING:
                sendPrint(f"[PROCESS] Matching response to command ID {command_id}: {request.description}")
                # Check if command has timed out
                if time.time() - request.sent_time > request.timeout:
                    sendPrint(f"[PROCESS] Command {command_id} timed out")
                    to_timeout.append(command_id)
                else:
                    # Match this response to this command
                    sendPrint(f"[PROCESS] Command {command_id} completed successfully")
                    to_complete = command_id
                break
        
        # Mark any other timed out commands
        current_time = time.time()
        for command_id, request in _command_requests.items():
            if (request.state == CommandState.PENDING and 
                current_time - request.sent_time > request.timeout):
                to_timeout.append(command_id)

    # Perform transitions outside the lock to avoid deadlocks
    for command_id in to_timeout:
        _transitionToTimeout(command_id)
    if to_complete is not None:
        sendPrint(f"[PROCESS] About to call _transitionToCompleted for command {to_complete}")
        try:
            _transitionToCompleted(to_complete, data)
            sendPrint(f"[PROCESS] _transitionToCompleted call completed for command {to_complete}")
        except Exception as e:
            sendPrint(f"[PROCESS] ERROR in _transitionToCompleted: {e}")
            import traceback
            traceback.print_exc()

def _timeout_checker():
    """Background thread that checks for timed-out commands"""
    global _timeout_running
    sendPrint("[TIMEOUT] Timeout checker thread started")
    
    while _timeout_running:
        try:
            current_time = time.time()
            timed_out_commands = []
            
            with _command_lock:
                for command_id, request in _command_requests.items():
                    if (request.state == CommandState.PENDING and 
                        current_time - request.sent_time > request.timeout):
                        timed_out_commands.append(command_id)
            
            # Process timeouts outside the lock
            for command_id in timed_out_commands:
                sendPrint(f"[TIMEOUT] Command {command_id} timed out")
                _transitionToTimeout(command_id)
            
            time.sleep(0.1)  # Check every 100ms
        except Exception as e:
            sendPrint(f"[TIMEOUT] Error in timeout checker: {e}")
            time.sleep(1)
    
    sendPrint("[TIMEOUT] Timeout checker thread stopped")

def _serial_monitor():
    """Background thread that monitors serial port and processes responses"""
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
                
                # Process response through state machine
                _processResponse(data)
                
                # Also add to shared response queue for backward compatibility
                with _response_lock:
                    _response_queue.append((time.time(), data))
        except Exception as e:
            sendPrint(f"[SERIAL] Error reading: {e}")
            time.sleep(0.1)
    
    sendPrint("Serial monitor thread stopped")

def startMonitor():
    """Start the serial monitor thread"""
    global _monitor_running, _monitor_thread, _timeout_running, _timeout_thread
    
    if _monitor_running:
        sendPrint("Monitor already running")
        return
    
    sendPrint("Starting serial monitor thread...")
    _monitor_running = True
    _monitor_thread = threading.Thread(target=_serial_monitor, daemon=True)
    _monitor_thread.start()
    
    # Start timeout checker thread
    _timeout_running = True
    _timeout_thread = threading.Thread(target=_timeout_checker, daemon=True)
    _timeout_thread.start()
    sendPrint("Timeout checker started")
    
    time.sleep(0.5)  # Give threads time to start
    sendPrint("Serial monitor started")

def stopMonitor():
    """Stop the serial monitor thread"""
    global _monitor_running, _monitor_thread, _timeout_running, _timeout_thread
    
    if not _monitor_running:
        sendPrint("Monitor not running")
        return
    
    sendPrint("Stopping serial monitor thread...")
    _monitor_running = False
    _timeout_running = False
    
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=2)
    
    if _timeout_thread and _timeout_thread.is_alive():
        _timeout_thread.join(timeout=2)
    
    sendPrint("Serial monitor stopped")

def runSequentialCommands(command_sequence):
    """
    STATE MACHINE: Run a sequence of commands where each callback triggers the next command.
    
    Args:
        command_sequence: List of (command, description, timeout) tuples
    
    Flow:
    1. Send first command
    2. On success callback: send next command
    3. On failure callback: stop sequence
    4. Continue until all commands sent or failure occurs
    """
    if not command_sequence:
        sendPrint("[SEQ] No commands to run")
        return
    
    current_index = [0]  # Use list to make it mutable in nested function
    
    def nextCommandCallback(success, responses, description):
        if success:
            sendPrint(f"[SEQ] ✓ {description} completed")
            
            # Move to next command
            current_index[0] += 1
            
            if current_index[0] < len(command_sequence):
                # Send next command in sequence
                next_command, next_desc, next_timeout = command_sequence[current_index[0]]
                sendPrint(f"[SEQ] → Sending next command: {next_desc}")
                sendCommand(next_command, nextCommandCallback, next_timeout, next_desc)
            else:
                sendPrint("[SEQ] ✓ All commands completed successfully!")
        else:
            sendPrint(f"[SEQ] ✗ {description} failed - stopping sequence")
    
    # Start the sequence with first command
    first_command, first_desc, first_timeout = command_sequence[0]
    sendPrint(f"[SEQ] Starting command sequence: {first_desc}")
    sendCommand(first_command, nextCommandCallback, first_timeout, first_desc)

def detectBoardAddress():
    """
    STATE MACHINE: Detect board address using sequential command chain with raw serial writes.
    This function requires exclusive access to the serial port (no monitor thread running).
    Uses a special state machine pattern for address detection with raw writes.
    
    Returns:
        bool: True if address detected successfully, False otherwise
    """
    if not SERIAL_AVAILABLE:
        sendPrint("[ADDR] Simulation mode - simulating successful address detection")
        return True
    
    global addr1, addr2
    
    sendPrint("[ADDR] Starting address detection with state machine...")
    
    # Address detection state tracking
    detection_state = {
        'step': 0,  # 0=version, 1=bootloader, 2=bus_ping, 3=complete
        'attempts': 0,
        'max_attempts': 60,  # 30 seconds with 0.5s intervals
        'start_time': time.time(),
        'timeout': 30.0,
        'addr1': None,
        'addr2': None
    }
    
    def addressDetectionCallback(success, responses, description):
        nonlocal detection_state
        global addr1, addr2
        
        if success:
            sendPrint(f"[ADDR] ✓ {description} completed")
            
            # Process responses based on current step
            if detection_state['step'] == 0:  # Version command
                detection_state['step'] = 1
                sendPrint("[ADDR] → Moving to bootloader command...")
                sendCommand(b'\x4e', addressDetectionCallback, 1.0, "Bootloader command (RAW)")
                
            elif detection_state['step'] == 1:  # Bootloader command
                detection_state['step'] = 2
                sendPrint("[ADDR] → Moving to bus ping commands...")
                sendCommand(b'\x87\x00\x00\x07', addressDetectionCallback, 1.0, "Bus ping command (RAW)")
                
            elif detection_state['step'] == 2:  # Bus ping command
                # Check if we got a valid address response
                if responses and len(responses) > 0:
                    response_data = responses[0][1]  # Get data from (timestamp, data) tuple
                    if len(response_data) > 5:
                        # Parse address from response: 87 00 06 06 50 63
                        detection_state['addr1'] = response_data[4]
                        detection_state['addr2'] = response_data[5]
                        addr1 = detection_state['addr1']  # Set global variables
                        addr2 = detection_state['addr2']
                        sendPrint(f"[ADDR] ✓ Board address detected: {hex(detection_state['addr1'])} {hex(detection_state['addr2'])}")
                        detection_state['step'] = 3
                        sendPrint("[ADDR] ✓ Address detection complete!")
                        return
                
                # No valid address yet, try again
                detection_state['attempts'] += 1
                if detection_state['attempts'] >= detection_state['max_attempts']:
                    sendPrint("[ADDR] ✗ Address detection failed after maximum attempts")
                    return
                
                if time.time() - detection_state['start_time'] > detection_state['timeout']:
                    sendPrint("[ADDR] ✗ Address detection failed after timeout")
                    return
                
                sendPrint(f"[ADDR] → Retrying bus ping (attempt {detection_state['attempts']})...")
                sendCommand(b'\x87\x00\x00\x07', addressDetectionCallback, 1.0, "Bus ping retry (RAW)")
        else:
            sendPrint(f"[ADDR] ✗ {description} failed")
            if detection_state['step'] < 2:
                # Version or bootloader failed - continue anyway
                detection_state['step'] += 1
                if detection_state['step'] == 1:
                    sendCommand(b'\x4e', addressDetectionCallback, 1.0, "Bootloader command (RAW)")
                elif detection_state['step'] == 2:
                    sendCommand(b'\x87\x00\x00\x07', addressDetectionCallback, 1.0, "Bus ping command (RAW)")
            else:
                # Bus ping failed - retry or give up
                detection_state['attempts'] += 1
                if detection_state['attempts'] >= detection_state['max_attempts']:
                    sendPrint("[ADDR] ✗ Address detection failed after maximum attempts")
                    return
                
                if time.time() - detection_state['start_time'] > detection_state['timeout']:
                    sendPrint("[ADDR] ✗ Address detection failed after timeout")
                    return
                
                sendPrint(f"[ADDR] → Retrying bus ping (attempt {detection_state['attempts']})...")
                sendCommand(b'\x87\x00\x00\x07', addressDetectionCallback, 1.0, "Bus ping retry (RAW)")
    
    # Start the address detection sequence
    sendPrint("[ADDR] Starting address detection sequence...")
    sendCommand(b'\x4d', addressDetectionCallback, 1.0, "Version command (RAW)")
    
    # Wait for completion with proper synchronization
    # Since monitor thread is now running, we need to wait for the state machine to complete
    max_wait_time = 35  # Maximum wait time in seconds
    start_wait = time.time()
    
    while detection_state['step'] < 3 and (time.time() - start_wait) < max_wait_time:
        time.sleep(0.1)  # Check every 100ms
    
    if detection_state['step'] == 3:
        sendPrint("[ADDR] ✓ Address detection completed successfully")
        return True
    else:
        sendPrint("[ADDR] ✗ Address detection timed out")
        return False

def checkBoardStatus():
    """
    STATE MACHINE: Check if the board is already properly initialized by testing the menu.py initialization sequence.
    Uses sequential command chain to test all required commands.
    Returns True if board is already initialized, False if it needs initialization.
    """
    if not SERIAL_AVAILABLE:
        sendPrint("[STATUS] Simulation mode - assuming board needs initialization")
        return False
    
    sendPrint("[STATUS] Checking if board is already properly initialized...")
    
    # Track test results
    test_results = [False]  # Use list to make it mutable in nested function
    
    def statusTestCallback(success, responses, description):
        if success:
            sendPrint(f"[STATUS] ✓ {description} works")
            # If this is the last command in the sequence, board is initialized
            if "button status" in description:
                sendPrint("[STATUS] ✓ Board is already initialized!")
        else:
            sendPrint(f"[STATUS] ✗ {description} failed - board needs initialization")
            sendPrint("[STATUS] → Starting initialization sequence...")
            # Start initialization sequence
            initializeBoard()
    
    # Create test sequence for board status check
    test_sequence = [
        (b'\x4d', "Testing version command...", 1.0),
        (b'\xb0\x00\x07', "Testing LED off command...", 1.0),
        (b'\xb1\x00\x0a', "Testing beep command...", 1.0),
        (b'\x83', "Testing field changes command...", 1.0),
        (b'\x94', "Testing button status command...", 1.0)
    ]
    
    # Run the test sequence
    runSequentialCommands(test_sequence)

def initializeBoard():
    """
    STATE MACHINE: Initialize the board with the exact sequence from menu.py lines 176-179.
    Uses sequential command chain where each successful response triggers the next command.
    This is the actual initialization sequence used by the main application.
    """
    sendPrint("[INIT] Starting board initialization (menu.py sequence)...")
    
    if not SERIAL_AVAILABLE:
        sendPrint("[INIT] Running in simulation mode - no actual hardware")
        return True
    
    # Create initialization sequence (same as menu.py lines 176-179)
    init_sequence = [
        (b'\xb0\x00\x07', "Turning LEDs off...", 1.0),
        (b'\xb1\x00\x0a', "Sending power-on beep...", 1.0),
        (b'\x83', "Clearing serial buffer (field changes)...", 1.0),
        (b'\x94', "Clearing serial buffer (button status)...", 1.0)
    ]
    
    # Run the initialization sequence using state machine
    runSequentialCommands(init_sequence)
    
    sendPrint("[INIT] Board initialization sequence completed")
    return True

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

def closeSerial():
    stopMonitor()
    if SERIAL_AVAILABLE and ser:
        ser.close()

if __name__ == "__main__":
    sendPrint("Starting DGT Centaur serial helper...")
    
    # Step 1: Start monitor thread FIRST (needed for state machine responses)
    sendPrint("Starting serial monitor thread...")
    startMonitor()
    time.sleep(0.5)  # Give monitor thread time to start
    
    # Step 2: Detect board address using state machine (now monitor thread is running)
    if detectBoardAddress():
        sendPrint("✓ Board address detection successful!")
        sendPrint(f"✓ Using detected address: {hex(addr1)} {hex(addr2)}")
        
        # Step 3: Check if board is already initialized, initialize if needed
        checkBoardStatus()
    else:
        sendPrint("✗ Board address detection failed!")
        sendPrint("✗ LED and sound commands will not work")
        sendPrint("✗ Starting monitor thread anyway for debugging...")
    
    try:
        sendPrint("Serial monitor running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sendPrint("\nStopping serial monitor...")
        stopMonitor()
        closeSerial()
        sendPrint("Serial monitor stopped.")
