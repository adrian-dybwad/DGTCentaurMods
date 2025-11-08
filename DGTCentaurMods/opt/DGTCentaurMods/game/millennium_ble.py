# Emulate the Millennium Chesslink protocol over BLE (Bluetooth Low Energy)
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
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

from DGTCentaurMods.game import gamemanager
from DGTCentaurMods.display import epaper
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController

import time
import threading
import os
import psutil
import dbus
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic
from DGTCentaurMods.thirdparty.bletools import BleTools

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

# Global state
kill = 0
E2ROM = bytearray([0] * 256)
sendstatewithoutrequest = 1
curturn = 1
rx_buffer = bytearray()
rx_lock = threading.Lock()

def keyCallback(key):
	global kill
	log.info("Key event received: " + str(key))
	if key == gamemanager.board.Key.BACK:
		log.info("setting kill")
		kill = 1
	if key == gamemanager.board.Key.PLAY:
		# Send the board state again
		board.beep(board.SOUND_GENERAL)
		bs = gamemanager.getFEN()
		bs = bs.replace("/", "")
		bs = bs.replace("1", ".")
		bs = bs.replace("2", "..")
		bs = bs.replace("3", "...")
		bs = bs.replace("4", "....")
		bs = bs.replace("5", ".....")
		bs = bs.replace("6", "......")
		bs = bs.replace("7", ".......")
		bs = bs.replace("8", "........")
		resp = 's'
		for x in range(0, 64):
			resp = resp + bs[x]
		log.info("sending status on change")
		sendMillenniumCommand(resp)

def eventCallback(event):
	global curturn
	global sendstatewithoutrequest
	if event == gamemanager.EVENT_NEW_GAME:
		epaper.writeText(0,"New Game")
		epaper.writeText(1,"               ")
		curturn = 1
		epaper.drawFen(gamemanager.getFEN())
		log.info("sending state")
		bs = gamemanager.getFEN()
		bs = bs.replace("/", "")
		bs = bs.replace("1", ".")
		bs = bs.replace("2", "..")
		bs = bs.replace("3", "...")
		bs = bs.replace("4", "....")
		bs = bs.replace("5", ".....")
		bs = bs.replace("6", "......")
		bs = bs.replace("7", ".......")
		bs = bs.replace("8", "........")
		resp = 's'
		for x in range(0, 64):
			resp = resp + bs[x]
		log.info(resp)
		sendMillenniumCommand(resp)
		board.ledsOff()
	if event == gamemanager.EVENT_WHITE_TURN:
		curturn = 1
		log.info("white turn event")
		epaper.writeText(0,"White turn")
	if event == gamemanager.EVENT_BLACK_TURN:
		curturn = 0
		log.info("black turn event")
		epaper.writeText(0,"Black turn")

	if type(event) == str:
		if event.startswith("Termination."):
			board.ledsOff()
			epaper.writeText(1,event[12:])
			time.sleep(10)
			kill = 1

def moveCallback(move):
	global sendstatewithoutrequest
	epaper.drawFen(gamemanager.getFEN())
	epaper.writeText(9, move)
	bs = gamemanager.getFEN()
	bs = bs.replace("/", "")
	bs = bs.replace("1", ".")
	bs = bs.replace("2", "..")
	bs = bs.replace("3", "...")
	bs = bs.replace("4", "....")
	bs = bs.replace("5", ".....")
	bs = bs.replace("6", "......")
	bs = bs.replace("7", ".......")
	bs = bs.replace("8", "........")
	resp = 's'
	for x in range(0, 64):
		resp = resp + bs[x]
	log.info("sending status on change")
	sendMillenniumCommand(resp)

# Activate the epaper
epaper.initEpaper()
board.ledsOff()
epaper.writeText(0,'Connect remote')
epaper.writeText(1,'Device Now')

# Create Bluetooth controller instance and start pairing thread
# Use "MILLENNIUM CHESS" device name for ChessLink app compatibility
bluetooth_controller = BluetoothController(device_name="MILLENNIUM CHESS")
bluetooth_controller.enable_bluetooth()
bluetooth_controller.set_device_name("MILLENNIUM CHESS")
pairThread = bluetooth_controller.start_pairing_thread()

# Small delay to let bt-agent initialize
time.sleep(2.5)

# Kill rfcomm if it is started
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

# BLE Advertisement
class UARTAdvertisement(Advertisement):
	"""BLE advertisement for Millennium ChessLink service"""
	def __init__(self, index):
		Advertisement.__init__(self, index, "peripheral")
		# Try "MILLENNIUM CHESS" as device name - this is what ChessLink might expect
		# Also try shorter "Chess Link" if the full name doesn't work
		self.add_local_name("MILLENNIUM CHESS")
		self.include_tx_power = True
		# Millennium ChessLink service UUID
		self.add_service_uuid("94f39d29-7d6d-437d-973b-fba39e49d4ee")
		log.info("BLE Advertisement initialized with name: MILLENNIUM CHESS")
		log.info("BLE Advertisement service UUID: 94f39d29-7d6d-437d-973b-fba39e49d4ee")
	
	def register_ad_callback(self):
		"""Callback when advertisement is successfully registered"""
		log.info("Millennium BLE advertisement registered successfully")
		log.info("Device should now be discoverable as 'MILLENNIUM CHESS'")
	
	def register_ad_error_callback(self, error):
		"""Callback when advertisement registration fails"""
		log.error(f"Failed to register Millennium BLE advertisement: {error}")
		log.error("Check that BlueZ is running and BLE is enabled")
	
	def register(self):
		"""Register advertisement with iOS/macOS compatible options"""
		try:
			bus = BleTools.get_bus()
			adapter = BleTools.find_adapter(bus)
			log.info(f"Found Bluetooth adapter: {adapter}")
			
			ad_manager = dbus.Interface(
				bus.get_object("org.bluez", adapter),
				"org.bluez.LEAdvertisingManager1")
			
			# iOS/macOS compatibility options
			options = {
				"MinInterval": dbus.UInt16(0x0014),  # 20ms
				"MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
			}
			
			log.info("Registering Millennium BLE advertisement with iOS/macOS compatible intervals")
			log.info(f"Advertisement path: {self.get_path()}")
			ad_manager.RegisterAdvertisement(
				self.get_path(),
				options,
				reply_handler=self.register_ad_callback,
				error_handler=self.register_ad_error_callback)
		except Exception as e:
			log.error(f"Exception during BLE advertisement registration: {e}")
			import traceback
			log.error(traceback.format_exc())

# BLE Service
class UARTService(Service):
	"""BLE UART service for Millennium ChessLink protocol"""
	tx_obj = None
	
	# Millennium ChessLink service UUID
	UART_SVC_UUID = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
	
	def __init__(self, index):
		Service.__init__(self, index, self.UART_SVC_UUID, True)
		self.add_characteristic(UARTTXCharacteristic(self))
		self.add_characteristic(UARTRXCharacteristic(self))

# RX Characteristic - receives commands from BLE client
class UARTRXCharacteristic(Characteristic):
	"""BLE RX characteristic - receives Millennium protocol commands"""
	UARTRX_CHARACTERISTIC_UUID = "94f39d29-7d6d-437d-973b-fba39e49d4ef"
	
	def __init__(self, service):
		Characteristic.__init__(
			self, self.UARTRX_CHARACTERISTIC_UUID,
			["write"], service)
	
	def WriteValue(self, value, options):
		"""When the remote device writes data via BLE, process Millennium commands"""
		global running, rx_buffer, rx_lock, kill
		if kill:
			return
		
		log.info("Received message from BLE: " + str(value))
		bytes_data = bytearray()
		for i in range(0, len(value)):
			bytes_data.append(value[i])
		
		log.debug(f"BLE -> Millennium: {' '.join(f'{b:02x}' for b in bytes_data)}")
		
		# Add to RX buffer and process commands
		with rx_lock:
			rx_buffer.extend(bytes_data)
			processMillenniumCommands()

# TX Characteristic - sends responses to BLE client
class UARTTXCharacteristic(Characteristic):
	"""BLE TX characteristic - sends Millennium protocol responses"""
	UARTTX_CHARACTERISTIC_UUID = "94f39d29-7d6d-437d-973b-fba39e49d4f0"
	
	def __init__(self, service):
		Characteristic.__init__(
			self, self.UARTTX_CHARACTERISTIC_UUID,
			["read", "notify"], service)
		self.notifying = False
	
	def sendMessage(self, data):
		"""Send a message via BLE notification"""
		if not self.notifying:
			return
		log.debug(f"Millennium -> BLE: {' '.join(f'{b:02x}' for b in data)}")
		tosend = bytearray()
		for x in range(0, len(data)):
			tosend.append(data[x])
		UARTService.tx_obj.updateValue(tosend)
	
	def StartNotify(self):
		"""Called when BLE client subscribes to notifications"""
		log.info("BLE client started notifications")
		UARTService.tx_obj = self
		self.notifying = True
		return self.notifying
	
	def StopNotify(self):
		"""Called when BLE client unsubscribes from notifications"""
		if not self.notifying:
			return
		log.info("BLE client stopped notifications")
		self.notifying = False
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

def odd_par(b):
	"""Calculate odd parity for a byte"""
	byte = b & 127
	par = 1
	for _ in range(7):
		bit = byte & 1
		byte = byte >> 1
		par = par ^ bit
	if par == 1:
		byte = b | 128
	else:
		byte = b & 127
	return byte

def sendMillenniumCommand(txt):
	"""Send a Millennium protocol command via BLE"""
	global UARTService
	log.info("send command: " + txt)
	cs = 0
	tosend = bytearray(b'')
	for el in range(0, len(txt)):
		tosend.append(odd_par(ord(txt[el])))
		cs = cs ^ ord(txt[el])
	h = "0x{:02x}".format(cs)
	h1 = h[2:3]
	h2 = h[3:4]
	tosend.append(odd_par(ord(h1)))
	tosend.append(odd_par(ord(h2)))
	log.info("sending: " + tosend.hex())
	
	# Send via BLE TX characteristic
	if UARTService.tx_obj is not None:
		UARTService.tx_obj.sendMessage(tosend)

def processMillenniumCommands():
	"""Process commands from RX buffer"""
	global rx_buffer, kill, E2ROM, sendstatewithoutrequest
	
	# Process commands byte by byte
	while len(rx_buffer) > 0 and not kill:
		# Read command byte (strip parity)
		cmd_byte = rx_buffer[0] & 127
		cmd = chr(cmd_byte)
		log.info(f"Processing command: {cmd} (0x{cmd_byte:02x})")
		
		handled = False
		
		if cmd == 'V':
			# Version request - need 2 more bytes (checksum)
			if len(rx_buffer) < 3:
				break
			rx_buffer = rx_buffer[3:]  # Remove V + 2 checksum bytes
			sendMillenniumCommand("v3130")
			handled = True
		
		elif cmd == 'I':
			# Identity - need 4 data bytes + 2 checksum bytes
			if len(rx_buffer) < 7:
				break
			data = rx_buffer[1:5]
			log.info("hit i: " + data.hex())
			rx_buffer = rx_buffer[7:]  # Remove I + 4 data + 2 checksum
			sendMillenniumCommand("i0055mm\n")
			handled = True
		
		elif cmd == 'S':
			# Status request - need 2 checksum bytes
			if len(rx_buffer) < 3:
				break
			rx_buffer = rx_buffer[3:]  # Remove S + 2 checksum
			bs = gamemanager.getFEN()
			bs = bs.replace("/", "")
			bs = bs.replace("1", ".")
			bs = bs.replace("2", "..")
			bs = bs.replace("3", "...")
			bs = bs.replace("4", "....")
			bs = bs.replace("5", ".....")
			bs = bs.replace("6", "......")
			bs = bs.replace("7", ".......")
			bs = bs.replace("8", "........")
			resp = 's'
			for x in range(0, 64):
				resp = resp + bs[x]
			sendMillenniumCommand(resp)
			handled = True
		
		elif cmd == 'W':
			# Write E2ROM - need 4 hex chars (2 addr + 2 value) + 2 checksum
			if len(rx_buffer) < 7:
				break
			h1 = rx_buffer[1] & 127
			h2 = rx_buffer[2] & 127
			hexn = '0x' + chr(h1) + chr(h2)
			address = int(str(hexn), 16)
			h3 = rx_buffer[3] & 127
			h4 = rx_buffer[4] & 127
			hexn = '0x' + chr(h3) + chr(h4)
			value = int(str(hexn), 16)
			log.info(f"Write E2ROM: address={address}, value={value}")
			rx_buffer = rx_buffer[7:]  # Remove W + 4 hex + 2 checksum
			E2ROM[address] = value
			sendMillenniumCommand(str('w' + chr(h1) + chr(h2) + chr(h3) + chr(h4)))
			if address == 2 and (value & 0x01 == 1):
				sendstatewithoutrequest = 0
			handled = True
		
		elif cmd == 'X':
			# Extinguish LEDs - need 2 checksum bytes
			if len(rx_buffer) < 3:
				break
			rx_buffer = rx_buffer[3:]  # Remove X + 2 checksum
			board.ledsOff()
			sendMillenniumCommand('x')
			handled = True
		
		elif cmd == 'R':
			# Read E2ROM - need 2 hex chars (address) + 2 checksum
			if len(rx_buffer) < 5:
				break
			h1 = rx_buffer[1] & 127
			h2 = rx_buffer[2] & 127
			hexn = '0x' + chr(h1) + chr(h2)
			address = int(str(hexn), 16)
			value = E2ROM[address]
			h = str(hex(value)).upper()
			h3 = h[2:3] if len(h) > 2 else '0'
			h4 = h[3:4] if len(h) > 3 else '0'
			rx_buffer = rx_buffer[5:]  # Remove R + 2 hex + 2 checksum
			sendMillenniumCommand(str(chr(h1) + chr(h2) + str(h3) + str(h4)))
			handled = True
		
		elif cmd == 'L':
			# LED pattern - need 2 slot time + 81 LED bytes + 2 checksum = 85 bytes total
			if len(rx_buffer) < 85:
				break
			# Skip slot time (2 bytes)
			mpattern = bytearray([0] * 81)
			for x in range(0, 81):
				h1 = rx_buffer[3 + x*2] & 127
				h2 = rx_buffer[4 + x*2] & 127
				hexn = '0x' + chr(h1) + chr(h2)
				v = int(str(hexn), 16)
				mpattern[x] = v
			rx_buffer = rx_buffer[85:]  # Remove L + 2 slot + 81*2 hex + 2 checksum
			
			# Convert to Centaur LED pattern
			centaurpattern = bytearray([0] * 64)
			ledmap = [
				[7, 8, 16, 17], [16, 17, 25, 26], [25, 26, 34, 35], [34, 35, 43, 44], [43, 44, 52, 53], [52, 53, 61, 62],
				[61, 62, 70, 71], [70, 71, 79, 80],
				[6, 7, 15, 16], [15, 16, 24, 25], [24, 25, 33, 34], [33, 34, 42, 43], [42, 43, 51, 52], [51, 52, 60, 61],
				[60, 61, 69, 70], [69, 70, 78, 79],
				[5, 6, 14, 15], [14, 15, 23, 24], [23, 24, 32, 33], [32, 33, 41, 42], [41, 42, 50, 51], [50, 51, 59, 60],
				[59, 60, 68, 69], [68, 69, 77, 78],
				[4, 5, 13, 14], [13, 14, 22, 23], [22, 23, 31, 32], [31, 32, 40, 41], [40, 41, 49, 50], [49, 50, 58, 59],
				[58, 59, 67, 68], [67, 68, 76, 77],
				[3, 4, 12, 13], [12, 13, 21, 22], [21, 22, 30, 31], [30, 31, 39, 40], [39, 40, 48, 49], [48, 49, 57, 58],
				[57, 58, 66, 67], [66, 67, 75, 76],
				[2, 3, 11, 12], [11, 12, 20, 21], [20, 21, 29, 30], [29, 30, 38, 39], [38, 39, 47, 48], [47, 48, 56, 57],
				[56, 57, 65, 66], [65, 66, 74, 75],
				[1, 2, 10, 11], [10, 11, 19, 20], [19, 20, 28, 29], [28, 29, 37, 38], [37, 38, 46, 47], [46, 47, 55, 56],
				[55, 56, 64, 65], [64, 65, 73, 74],
				[0, 1, 9, 10], [9, 10, 18, 19], [18, 19, 27, 28], [27, 28, 36, 37], [36, 37, 45, 46], [45, 46, 54, 55],
				[54, 55, 63, 64], [63, 64, 72, 73]
			]
			for x in range(0, 64):
				lmap = ledmap[x]
				if mpattern[lmap[0]] > 0:
					centaurpattern[x] = centaurpattern[x] + 1
				if mpattern[lmap[1]] > 0:
					centaurpattern[x] = centaurpattern[x] + 1
				if mpattern[lmap[2]] > 0:
					centaurpattern[x] = centaurpattern[x] + 1
				if mpattern[lmap[3]] > 0:
					centaurpattern[x] = centaurpattern[x] + 1
			# Take only squares where all lights are lit
			for x in range(0, 64):
				if centaurpattern[x] != 4:
					centaurpattern[x] = 0
			# Eliminate middle LED for 2-square moves
			for r in range(0, 8):
				for t in range(0, 6):
					if centaurpattern[(r * 8) + t] == 4 and centaurpattern[(r * 8) + (t + 1)] == 4 and centaurpattern[(r * 8) + (t + 2)] == 4:
						centaurpattern[(r * 8) + (t + 1)] = 0
			for r in range(0, 6):
				for t in range(0, 8):
					if centaurpattern[(r * 8) + t] == 4 and centaurpattern[((r + 1) * 8) + t] == 4 and centaurpattern[((r + 2) * 8) + t] == 4:
						centaurpattern[((r + 1) * 8) + t] = 0
			board.ledsOff()
			ledfields = []
			for x in range(0, 64):
				if centaurpattern[x] > 0:
					ledfields.append(x)
			if len(ledfields) > 0:
				board.ledArray(ledfields, speed=5, intensity=5)
			sendMillenniumCommand("l")
			handled = True
		
		elif cmd == 'T':
			# Reset - need 2 checksum bytes
			if len(rx_buffer) < 3:
				break
			rx_buffer = rx_buffer[3:]  # Remove T + 2 checksum
			sendMillenniumCommand("t")
			sendstatewithoutrequest = 1
			time.sleep(3)
			handled = True
		
		if not handled:
			log.info(f"Unhandled command: {cmd}")
			# Remove first byte and try again
			if len(rx_buffer) > 0:
				rx_buffer = rx_buffer[1:]
			else:
				break

# Initialize BLE application
running = True
app = Application()
app.add_service(UARTService(0))
app.register()

adv = UARTAdvertisement(0)
adv.register()

log.info("Millennium BLE service registered and advertising")
log.info("Waiting for BLE connection...")
log.info("To verify BLE advertisement is working, run: sudo hcitool lescan")
log.info("You should see 'MILLENNIUM CHESS' in the scan results")

# Subscribe to game manager
gamemanager.subscribeGame(eventCallback, moveCallback, keyCallback)
epaper.writeText(0,"Place pieces in")
epaper.writeText(1,"Starting Pos")

# Main loop - run BLE application mainloop
try:
	app.run()
except KeyboardInterrupt:
	log.info("Keyboard interrupt received")
	kill = 1
	running = False
except Exception as e:
	log.error(f"Error in main loop: {e}")
	kill = 1
	running = False

# Cleanup
log.info("Shutting down...")
kill = 1
running = False
time.sleep(0.5)

try:
	app.quit()
except Exception:
	pass

log.info("Disconnected")
time.sleep(1)

log.info("Exiting millennium_ble.py")

