# DGT Centaur Simple Board Controller
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# SimpleCentaur (simple_centaur.py) is a minimal implementation that:
# - Discovers the board
# - Constructs packets for commands
# - Sends commands and outputs return bytes directly to serial port
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
import time
import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional
from types import SimpleNamespace

from DGTCentaurMods.board.logging import log

# Unified command registry (same as sync_centaur)
@dataclass(frozen=True)
class CommandSpec:
    cmd: bytes
    expected_resp_type: int = None
    default_data: Optional[bytes] = None

COMMANDS: Dict[str, CommandSpec] = {
    "DGT_BUS_SEND_87":        CommandSpec(0x87, 0x87), # Sent after initial init but before ADDR1 ADDR2 is populated. This is a SHORT command.
    "DGT_BUS_SEND_SNAPSHOT_F0":  CommandSpec(0xf0, 0xF0, b'\x7f'), # Sent after initial ledsOff().
    "DGT_BUS_SEND_SNAPSHOT_F4":  CommandSpec(0xf4, 0xF4, b'\x7f'), # Sent after F0 is called.
    "DGT_BUS_SEND_96":  CommandSpec(0x96, 0xb2), # Sent after F4 is called. This is a SHORT command.

    "DGT_BUS_SEND_STATE":     CommandSpec(0x82, 0x83),
    "DGT_BUS_SEND_CHANGES":   CommandSpec(0x83, 0x85),
    "DGT_SEND_BATTERY_INFO":  CommandSpec(0x98, 0xB5),
    "SOUND_GENERAL":          CommandSpec(0xb1, None, b'\x4c\x08'),
    "SOUND_FACTORY":          CommandSpec(0xb1, None, b'\x4c\x40'),
    "SOUND_POWER_OFF":        CommandSpec(0xb1, None, b'\x4c\x08\x48\x08'),
    "SOUND_POWER_ON":         CommandSpec(0xb1, None, b'\x48\x08\x4c\x08'),
    "SOUND_WRONG":            CommandSpec(0xb1, None, b'\x4e\x0c\x48\x10'),
    "SOUND_WRONG_MOVE":       CommandSpec(0xb1, None, b'\x48\x08'),
    "DGT_SLEEP":              CommandSpec(0xb2, 0xB1, b'\x0a'),
    "LED_OFF_CMD":            CommandSpec(0xb0, None, b'\x00'),
    "LED_FLASH_CMD":          CommandSpec(0xb0, None, b'\x05\x0a\x00\x01'),
    "DGT_NOTIFY_EVENTS_58":      CommandSpec(0x58),
    "DGT_NOTIFY_EVENTS_43":      CommandSpec(0x43),
    "DGT_RETURN_BUSADRES":    CommandSpec(0x46, 0x90),
    "DGT_SEND_TRADEMARK":     CommandSpec(0x97, 0xb4),
}

# Fast lookups
CMD_BY_NAME = {name: spec for name, spec in COMMANDS.items()}

# Export name namespace for commands, e.g. command.LED_OFF_CMD -> "LED_OFF_CMD"
command = SimpleNamespace(**{name: name for name in COMMANDS.keys()})

__all__ = ['SimpleCentaur', 'command']


class SimpleCentaur:
    """DGT Centaur Simple Board Controller
    
    Minimal implementation that:
    - Bypasses discovery and uses fixed addresses (addr1=0x3e, addr2=0x5e)
    - Constructs packets for commands
    - Sends commands and outputs return bytes directly to serial port
    
    Usage:
        centaur = SimpleCentaur(developer_mode=False)
        centaur.sendCommand("DGT_BUS_SEND_STATE")
    """
    
    def __init__(self, developer_mode=False):
        """
        Initialize serial connection to the board.
        
        Args:
            developer_mode (bool): If True, use virtual serial ports via socat
        """
        self.ser = None
        self.addr1 = 0x3e
        self.addr2 = 0x5e
        self.developer_mode = developer_mode
        self.ready = True
        self.listener_running = True
        self.listener_thread = None
        
        self._initialize()
    
    def _initialize(self):
        """Open serial connection based on mode"""
        if self.developer_mode:
            log.debug("Developer mode enabled - setting up virtual serial port")
            os.system("socat -d -d pty,raw,echo=0 pty,raw,echo=0 &")
            time.sleep(10)
            self.ser = serial.Serial("/dev/pts/2", baudrate=1000000, timeout=5.0)
        else:
            try:
                self.ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=5.0)
                self.ser.isOpen()
            except:
                self.ser.close()
                self.ser.open()
        
        log.info("Serial port opened successfully")
        
        # Start listener thread
        self.listener_running = True
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()
        log.info("Serial listener thread started")


    
    def _listener_thread(self):
        """Continuously listen for data on the serial port and print it"""
        log.info("Listening for serial data...")
        while self.listener_running:
            try:
                if self.ser and self.ser.is_open:
                    byte = self.ser.read(1)
                    if byte:
                        log.info(f"[SERIAL IN] {byte[0]:02x}")
                else:
                    time.sleep(0.1)
            except Exception as e:
                if self.listener_running:
                    log.error(f"Listener error: {e}")
                time.sleep(0.1)
    
    def discover_board(self):
        """
        Discover the board address by sending discovery commands.
        """
        log.info("Starting board discovery...")
        
        # Send initial discovery bytes
        self.ser.write(bytes([0x4d]))
        self.ser.write(bytes([0x4e]))
        time.sleep(0.1)
        
        # Send DGT_BUS_SEND_87 command
        self.sendPacket(command.DGT_BUS_SEND_87)
        time.sleep(0.5)
        
        # Read response to get addresses
        response = self.ser.read(100)
        if len(response) >= 5:
            if response[0] == 0x87:
                self.addr1 = response[3]
                self.addr2 = response[4]
                self.ready = True
                log.info(f"Board discovered - addr1={hex(self.addr1)}, addr2={hex(self.addr2)}")
            else:
                log.warning(f"Unexpected response during discovery: {' '.join(f'{b:02x}' for b in response[:10])}")
        else:
            log.warning("No response received during discovery")
    
    def buildPacket(self, command, data):
        """Build a complete packet with command, addresses, data, and checksum"""
        tosend = bytearray([command])
        if data is not None:
            len_packet = len(data) + 6
            len_hi = (len_packet >> 7) & 0x7F
            len_lo = len_packet & 0x7F
            tosend.append(len_hi)
            tosend.append(len_lo)
        tosend.append(self.addr1 & 0xFF)
        tosend.append(self.addr2 & 0xFF)
        if data is not None:
            tosend.extend(data)
        tosend.append(self.checksum(tosend))
        return tosend
    
    def checksum(self, barr):
        """Calculate checksum for packet (sum of all bytes mod 128)"""
        csum = sum(bytes(barr))
        barr_csum = (csum % 128)
        return barr_csum
    
    def sendPacket(self, command_name: str, data: Optional[bytes] = None):
        """
        Send a packet to the board using a command name.
        
        Args:
            command_name: command name in COMMANDS (e.g., "LED_OFF_CMD")
            data: bytes for data payload; if None, use default_data from the named command if available
        """
        if not isinstance(command_name, str):
            raise TypeError("sendPacket requires a command name (str), e.g. command.LED_OFF_CMD")
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)
        tosend = self.buildPacket(spec.cmd, eff_data)
        log.info(f"sendPacket: {command_name} ({spec.cmd:02x}) {' '.join(f'{b:02x}' for b in tosend[:16])}")
        self.ser.write(tosend)
    
    def sendCommand(self, command_name: str, data: Optional[bytes] = None, timeout: float = 1.0):
        """
        Send a command and output any return bytes directly to the serial port.
        
        Args:
            command_name: command name in COMMANDS (e.g., "DGT_BUS_SEND_STATE")
            data: optional payload bytes
            timeout: seconds to wait for response
            
        Returns:
            bytes: raw bytes read from serial port
        """
        if not self.ready:
            raise RuntimeError("Board not discovered. Call discover_board() first.")
        
        # Send the command
        self.sendPacket(command_name, data)
        
        return b''
    
    def cleanup(self):
        """Close serial port and stop listener thread"""
        # Stop listener thread
        self.listener_running = False
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=2.0)
            log.info("Listener thread stopped")
        
        if self.ser:
            try:
                self.ser.close()
                log.info("Serial port closed")
            except Exception:
                pass
            self.ser = None
        self.ready = False

