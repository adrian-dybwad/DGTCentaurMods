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

from DGTCentaurMods.games import manager as gamemanager
from DGTCentaurMods.board import *
from DGTCentaurMods.epaper import ChessBoardWidget, GameAnalysisWidget, SplashScreen, GameOverWidget, TextWidget
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController

import time
import threading
import os
import psutil
import dbus
import signal
import sys
try:
	from gi.repository import GObject
except ImportError:
	import gobject as GObject
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic
from DGTCentaurMods.thirdparty.bletools import BleTools

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

# Global state
kill = 0
cleaned_up = False
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
	global chess_board_widget
	global kill
	if event == gamemanager.EVENT_NEW_GAME:
		curturn = 1
		if chess_board_widget is None:
			chess_board_widget = ChessBoardWidget(0, 20, gamemanager.getFEN())
			board.display_manager.add_widget(chess_board_widget)
		chess_board_widget.set_fen(gamemanager.getFEN())
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
		#widgets.write_text(0,"White turn")
	if event == gamemanager.EVENT_BLACK_TURN:
		curturn = 0
		log.info("black turn event")
		#widgets.write_text(0,"Black turn")

	if type(event) == str:
		if event.startswith("Termination."):
			board.ledsOff()
			#widgets.write_text(1,event[12:])
			time.sleep(10)
			kill = 1

def moveCallback(move):
	global sendstatewithoutrequest
	global chess_board_widget

	if chess_board_widget is None:
		chess_board_widget = ChessBoardWidget(0, 20, gamemanager.getFEN())
		board.display_manager.add_widget(chess_board_widget)
	chess_board_widget.set_fen(gamemanager.getFEN())
	#widgets.write_text(9, move)
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
board.ledsOff()
promise = board.init_display()
if promise:
	try:
		promise.result(timeout=10.0)
	except Exception as e:
		log.warning(f"Error initializing display: {e}")

board.display_manager.add_widget(TextWidget(50, 20, 88, 100, "Connect remote Device Now", background=3, font_size=18))

#game_analysis = GameAnalysisWidget(0, 144, 128, 80, bottom_color=bottom_color, analysis_engine=analysis_engine)
#board.display_manager.add_widget(game_analysis)
chess_board_widget = None

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
		# NOTE: Do NOT advertise service UUID in advertisement packet
		# Real Millennium Chess board does not include service UUIDs in advertisement
		# This prevents showing complete UUID list in scanner (nRF Connect)
		# Clients will discover services after connecting via GATT service discovery
		# self.add_service_uuid("49535343-FE7D-4AE5-8FA9-9FAFD205E455")  # REMOVED to match real board
		
		# Store MAC address for later use in advertisement
		self.mac_address = None
		
		log.info("BLE Advertisement initialized with name: MILLENNIUM CHESS")
		log.info("BLE Advertisement: Service UUID NOT included in advertisement (matches real Millennium Chess board)")
		log.info("BLE Advertisement: Service UUID will be discovered after connection via GATT")
	
	def register_ad_callback(self):
		"""Callback when advertisement is successfully registered"""
		log.info("Millennium BLE advertisement registered successfully")
		log.info("Device should now be discoverable as 'MILLENNIUM CHESS'")
		log.info("If ChessLink shows UUID instead of MAC address, the UUID may be a device identifier")
		log.info("The actual MAC address (B8:27:EB:21:D2:51) should be visible in BLE scan tools")
		log.info("ChessLink may be using a device UUID for identification - this may cause app freezing")
	
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
			
			# Get adapter properties interface
			adapter_props = dbus.Interface(
				bus.get_object("org.bluez", adapter),
				"org.freedesktop.DBus.Properties")
			
			# Configure adapter to allow unbonded connections (no pairing required)
			# Real Millennium Chess board allows unbonded connections
			# Note: Bondable is a D-Bus property, not a config file option
			try:
				# For unbonded BLE connections, we need to:
				# 1. Set Bondable=False (prevents bonding requirement)
				# 2. Set Pairable=False (prevents pairing requirement)
				# This allows clients to connect without pairing/bonding
				bondable_set = False
				pairable_set = False
				
				try:
					adapter_props.Set("org.bluez.Adapter1", "Bondable", dbus.Boolean(False))
					log.info("Adapter Bondable set to False (allows unbonded connections)")
					bondable_set = True
				except dbus.exceptions.DBusException as e:
					log.warning(f"Could not set Bondable property: {e}")
					log.warning("This may prevent unbonded connections - bonding may be required")
				
				try:
					adapter_props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(False))
					log.info("Adapter Pairable set to False (allows unbonded connections)")
					pairable_set = True
				except dbus.exceptions.DBusException as e:
					log.warning(f"Could not set Pairable property: {e}")
					log.warning("This may prevent unbonded connections - pairing may be required")
				
				# Verify the settings were applied
				try:
					current_bondable = adapter_props.Get("org.bluez.Adapter1", "Bondable")
					current_pairable = adapter_props.Get("org.bluez.Adapter1", "Pairable")
					log.info(f"Current adapter settings - Bondable: {current_bondable}, Pairable: {current_pairable}")
					
					if current_bondable or current_pairable:
						log.warning("=" * 60)
						log.warning("Adapter may still require bonding/pairing for connections")
						log.warning("If nRF Connect requires pairing, this is likely a BlueZ policy limitation")
						log.warning("Some BlueZ versions require bonding for BLE connections by default")
						log.warning("=" * 60)
					else:
						log.info("Adapter configured to allow unbonded connections (matches real Millennium Chess board)")
						log.info("Clients should be able to connect without pairing/bonding")
				except dbus.exceptions.DBusException as e:
					log.debug(f"Could not read adapter properties: {e}")
					
			except Exception as e:
				log.warning(f"Error configuring adapter for unbonded connections: {e}")
				import traceback
				log.warning(traceback.format_exc())
			
			# Get adapter MAC address and store it
			try:
				mac_address = adapter_props.Get("org.bluez.Adapter1", "Address")
				log.info(f"Bluetooth adapter MAC address: {mac_address}")
				# Store MAC address in advertisement object
				self.mac_address = mac_address
				
				# Note: BLE advertisement has 31-byte limit
				# Adding MAC to manufacturer/service data may exceed this limit
				# The MAC address should be visible in the BLE scan results automatically
				# when AddressType is 'public'
				log.info(f"MAC address will be included in BLE advertisement automatically (AddressType: public)")
			except Exception as e:
				log.warning(f"Could not get MAC address: {e}")
			
			# Configure adapter to use public MAC address instead of random
			# This is required for ChessLink to display MAC address instead of UUID
			# and to prevent app freezing
			# BlueZ privacy mode must be disabled in /etc/bluetooth/main.conf
			try:
				# Check if /etc/bluetooth/main.conf has privacy disabled
				import pathlib
				main_conf = pathlib.Path("/etc/bluetooth/main.conf")
				privacy_disabled = False
				if main_conf.exists():
					with open(main_conf, 'r') as f:
						content = f.read()
						if "Privacy = off" in content or "Privacy=off" in content:
							privacy_disabled = True
							log.info("Privacy mode is disabled in /etc/bluetooth/main.conf")
						else:
							log.warning("Privacy mode may be enabled in /etc/bluetooth/main.conf")
							log.warning("Add 'Privacy = off' under [General] section to use public MAC address")
				else:
					log.warning("/etc/bluetooth/main.conf not found - privacy mode status unknown")
				
				# Try to disable privacy mode via D-Bus (may not work on all systems)
				try:
					adapter_props.Set("org.bluez.Adapter1", "Privacy", dbus.Boolean(False))
					log.info("Disabled adapter Privacy mode via D-Bus (using public MAC address)")
					privacy_disabled = True
				except dbus.exceptions.DBusException as e:
					log.info(f"Privacy property not available via D-Bus: {e}")
					if not privacy_disabled:
						log.warning("Cannot disable privacy mode - ChessLink may show UUID instead of MAC")
						log.warning("To fix: Add 'Privacy = off' to /etc/bluetooth/main.conf under [General] section")
						log.warning("Then restart bluetooth service: sudo systemctl restart bluetooth")
			except Exception as e:
				log.warning(f"Could not configure adapter for public MAC address: {e}")
				log.warning("ChessLink may show UUID instead of MAC address and may freeze")
			
			ad_manager = dbus.Interface(
				bus.get_object("org.bluez", adapter),
				"org.bluez.LEAdvertisingManager1")
			
			# iOS/macOS compatibility options
			# Try to ensure we're using public address type
			# Note: The address type is typically controlled by the adapter's privacy settings
			options = {
				"MinInterval": dbus.UInt16(0x0014),  # 20ms
				"MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
			}
			
			# Check the actual AddressType value and try to set LE address to public MAC
			try:
				adapter_info = adapter_props.GetAll("org.bluez.Adapter1")
				address_type = adapter_info.get("AddressType", "unknown")
				mac_address = adapter_info.get("Address", "unknown")
				log.info(f"Adapter AddressType: {address_type}")
				log.info(f"Adapter MAC address: {mac_address}")
				
				if address_type != "public":
					log.warning(f"Adapter AddressType is '{address_type}', not 'public'")
					log.warning("Attempting to set LE address to public MAC address...")
					
					# Try to set the LE address to the public MAC using hciconfig
					import subprocess
					try:
						# First, check current LE address
						result_check = subprocess.run(
							['hciconfig', 'hci0'],
							capture_output=True,
							text=True,
							timeout=5
						)
						if result_check.returncode == 0:
							log.info(f"Current hci0 config: {result_check.stdout[:200]}")
						
						# Set LE address to public MAC address
						# Note: This may require the adapter to be down first
						# Format: hciconfig hci0 leaddr B8:27:EB:21:D2:51
						log.info(f"Setting LE address to: {mac_address}")
						result = subprocess.run(
							['sudo', 'hciconfig', 'hci0', 'leaddr', mac_address],
							capture_output=True,
							text=True,
							timeout=5
						)
						if result.returncode == 0:
							log.info(f"Successfully set LE address to public MAC: {mac_address}")
							# Small delay to let it take effect
							time.sleep(0.5)
							# Verify it was set
							result2 = subprocess.run(
								['hciconfig', 'hci0'],
								capture_output=True,
								text=True,
								timeout=5
							)
							if result2.returncode == 0:
								log.info(f"LE address verification output: {result2.stdout[:300]}")
						else:
							log.warning(f"Failed to set LE address (return code {result.returncode})")
							log.warning(f"Error output: {result.stderr}")
							log.warning("ChessLink may still show UUID instead of MAC address")
							log.warning("You may need to manually run: sudo hciconfig hci0 leaddr " + mac_address)
					except FileNotFoundError:
						log.warning("hciconfig not found - cannot set LE address")
						log.warning("Install bluez-hcidump or ensure hciconfig is available")
					except subprocess.TimeoutExpired:
						log.warning("hciconfig command timed out")
					except Exception as e:
						log.warning(f"Error setting LE address: {e}")
						import traceback
						log.warning(traceback.format_exc())
				else:
					log.info("Adapter AddressType is 'public' - MAC address should be visible")
			except Exception as e:
				log.debug(f"Could not check/set adapter AddressType: {e}")
			
			# Verify LE address is set correctly before advertising
			# This ensures the MAC address is used in BLE advertisements
			try:
				import subprocess
				result = subprocess.run(
					['hciconfig', 'hci0'],
					capture_output=True,
					text=True,
					timeout=5
				)
				if result.returncode == 0:
					output = result.stdout
					if 'LE Address' in output or 'BD Address' in output:
						log.info(f"LE/BD Address from hciconfig: {output[output.find('Address'):output.find('Address')+50]}")
					# Check if we need to set the LE address
					if mac_address and mac_address.replace(':', '') not in output.replace(' ', '').replace(':', ''):
						log.warning("MAC address not found in hciconfig output - LE address may not be set correctly")
			except Exception as e:
				log.debug(f"Could not verify LE address via hciconfig: {e}")
			
			log.info("Registering Millennium BLE advertisement with iOS/macOS compatible intervals")
			log.info(f"Advertisement path: {self.get_path()}")
			log.info(f"Expected MAC address in advertisement: {mac_address if 'mac_address' in locals() else 'unknown'}")
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
	"""BLE UART service for Millennium ChessLink protocol - Transparent UART service"""
	tx_obj = None
	
	# Millennium ChessLink Transparent UART service UUID (correct BLE service)
	UART_SVC_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
	
	def __init__(self, index):
		Service.__init__(self, index, self.UART_SVC_UUID, True)
		self.add_characteristic(UARTTXCharacteristic(self))
		self.add_characteristic(UARTRXCharacteristic(self))

# RX Characteristic - receives commands from BLE client (App TX → Peripheral RX)
class UARTRXCharacteristic(Characteristic):
	"""BLE RX characteristic - receives Millennium protocol commands from app"""
	# Millennium ChessLink App TX → Peripheral RX characteristic UUID
	UARTRX_CHARACTERISTIC_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3"
	
	def __init__(self, service):
		# Flags: Only capability flags, NO security flags (allows unbonded connections)
		# Security flags like "encrypt-read", "encrypt-write" would require bonding
		flags = ["write", "write-without-response"]
		log.info(f"UARTRXCharacteristic: Initializing with flags: {flags}")
		log.info(f"UARTRXCharacteristic: No security flags set (allows unbonded/unencrypted access)")
		Characteristic.__init__(
			self, self.UARTRX_CHARACTERISTIC_UUID,
			flags, service)
		
		# Log the properties that will be exposed to BlueZ
		props = self.get_properties()
		log.info(f"UARTRXCharacteristic: Properties to be registered: {props}")
		log.info(f"UARTRXCharacteristic: Path: {self.get_path()}")
	
	def WriteValue(self, value, options):
		"""When the remote device writes data via BLE, process Millennium commands"""
		global running, rx_buffer, rx_lock, kill
		if kill:
			return
		
		# Log security options passed by BlueZ
		# The 'options' dict may contain security-related flags that BlueZ is enforcing
		log.info(f"UARTRXCharacteristic.WriteValue: options={options}")
		if options:
			option_keys = list(options.keys()) if hasattr(options, 'keys') else str(options)
			log.info(f"UARTRXCharacteristic.WriteValue: option keys: {option_keys}")
			# Check for security-related options
			for key in options.keys() if hasattr(options, 'keys') else []:
				log.info(f"UARTRXCharacteristic.WriteValue: option['{key}'] = {options[key]}")
		
		try:
			bytes_data = bytearray()
			for i in range(0, len(value)):
				bytes_data.append(value[i])
			
			log.debug(f"BLE -> Millennium: {' '.join(f'{b:02x}' for b in bytes_data)}")
			
			# Add to RX buffer and process commands
			with rx_lock:
				rx_buffer.extend(bytes_data)
				processMillenniumCommands()
		except Exception as e:
			log.error(f"Error in WriteValue: {e}")
			import traceback
			log.error(traceback.format_exc())
			raise

# TX Characteristic - sends responses to BLE client (Peripheral TX → App RX)
class UARTTXCharacteristic(Characteristic):
	"""BLE TX characteristic - sends Millennium protocol responses via notifications"""
	# Millennium ChessLink Peripheral TX → App RX characteristic UUID
	UARTTX_CHARACTERISTIC_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"
	
	def __init__(self, service):
		# Flags: Only capability flags, NO security flags (allows unbonded connections)
		# Security flags like "encrypt-read", "secure-read" would require bonding
		flags = ["read", "notify"]
		log.info(f"UARTTXCharacteristic: Initializing with flags: {flags}")
		log.info(f"UARTTXCharacteristic: No security flags set (allows unbonded/unencrypted access)")
		Characteristic.__init__(
			self, self.UARTTX_CHARACTERISTIC_UUID,
			flags, service)
		self.notifying = False
		
		# Log the properties that will be exposed to BlueZ
		props = self.get_properties()
		log.info(f"UARTTXCharacteristic: Properties to be registered: {props}")
		log.info(f"UARTTXCharacteristic: Path: {self.get_path()}")
	
	def sendMessage(self, data):
		"""Send a message via BLE notification"""
		if not self.notifying:
			return
		log.debug(f"Millennium -> BLE: {' '.join(f'{b:02x}' for b in data)}")
		tosend = bytearray()
		for x in range(0, len(data)):
			tosend.append(data[x])
		UARTService.tx_obj.updateValue(tosend)
	
	def ReadValue(self, options):
		"""Read the characteristic value"""
		# Log security options passed by BlueZ
		log.info(f"UARTTXCharacteristic.ReadValue: options={options}")
		if options:
			option_keys = list(options.keys()) if hasattr(options, 'keys') else str(options)
			log.info(f"UARTTXCharacteristic.ReadValue: option keys: {option_keys}")
			# Check for security-related options
			for key in options.keys() if hasattr(options, 'keys') else []:
				log.info(f"UARTTXCharacteristic.ReadValue: option['{key}'] = {options[key]}")
		
		# Return empty value (not used for notifications)
		value = dbus.Array([], signature=dbus.Signature('y'))
		return value
	
	def StartNotify(self):
		"""Called when BLE client subscribes to notifications"""
		try:
			log.info("UARTTXCharacteristic.StartNotify: BLE client subscribing to notifications")
			log.info("UARTTXCharacteristic.StartNotify: No security options required (unbonded connection allowed)")
			UARTService.tx_obj = self
			self.notifying = True
			log.info("UARTTXCharacteristic.StartNotify: Notifications enabled successfully")
			return self.notifying
		except Exception as e:
			log.error(f"Error in StartNotify: {e}")
			import traceback
			log.error(traceback.format_exc())
			raise
	
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
		try:
			log.info("TX Characteristic ReadValue called by BLE client")
			value = bytearray()
			value.append(0)
			return value
		except Exception as e:
			log.error(f"Error in ReadValue: {e}")
			import traceback
			log.error(traceback.format_exc())
			raise

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

def parse_hex_byte_pair(rx_buffer, idx1, idx2):
	"""
	Safely parse two bytes as a hex pair.
	
	Args:
		rx_buffer: The receive buffer
		idx1: Index of first byte
		idx2: Index of second byte
		
	Returns:
		tuple: (value, is_valid) where value is the parsed integer if valid, None otherwise
	"""
	if idx2 >= len(rx_buffer):
		return None, False
	
	h1 = rx_buffer[idx1] & 127
	h2 = rx_buffer[idx2] & 127
	c1 = chr(h1)
	c2 = chr(h2)
	
	# Validate that both characters are valid hex digits
	if not (c1 in '0123456789ABCDEFabcdef' and c2 in '0123456789ABCDEFabcdef'):
		log.warning(f"Invalid hex characters: '{c1}' (0x{h1:02x}) and '{c2}' (0x{h2:02x})")
		return None, False
	
	try:
		hexn = '0x' + c1 + c2
		value = int(hexn, 16)
		return value, True
	except ValueError as e:
		log.warning(f"Failed to parse hex '{hexn}': {e}")
		return None, False

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

		#log.info(f"Processing command: {cmd} (0x{cmd_byte:02x})")
		
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
			address, valid = parse_hex_byte_pair(rx_buffer, 1, 2)
			if not valid:
				log.error("Invalid address in W command, skipping")
				rx_buffer = rx_buffer[1:]  # Skip the W byte and try next command
				break
			value, valid = parse_hex_byte_pair(rx_buffer, 3, 4)
			if not valid:
				log.error("Invalid value in W command, skipping")
				rx_buffer = rx_buffer[1:]  # Skip the W byte and try next command
				break
			h1 = rx_buffer[1] & 127
			h2 = rx_buffer[2] & 127
			h3 = rx_buffer[3] & 127
			h4 = rx_buffer[4] & 127
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
			address, valid = parse_hex_byte_pair(rx_buffer, 1, 2)
			if not valid:
				log.error("Invalid address in R command, skipping")
				rx_buffer = rx_buffer[1:]  # Skip the R byte and try next command
				break
			h1 = rx_buffer[1] & 127
			h2 = rx_buffer[2] & 127
			value = E2ROM[address]
			h = str(hex(value)).upper()
			h3 = h[2:3] if len(h) > 2 else '0'
			h4 = h[3:4] if len(h) > 3 else '0'
			rx_buffer = rx_buffer[5:]  # Remove R + 2 hex + 2 checksum
			sendMillenniumCommand(str(chr(h1) + chr(h2) + str(h3) + str(h4)))
			handled = True
		
		elif cmd == 'L':
			# LED pattern - need 1 byte command + 2 slot time + 81 LED values (each 2 hex bytes) + 2 checksum = 167 bytes total
			required_bytes = 1 + 2 + (81 * 2) + 2  # L + slot + 81*2 hex + checksum
			if len(rx_buffer) < required_bytes:
				break
			# Skip slot time (2 bytes)
			mpattern = bytearray([0] * 81)
			# Process all 81 LED values (each encoded as 2 hex bytes)
			led_processing_complete = True
			for x in range(0, 81):
				idx1 = 3 + x*2
				idx2 = 4 + x*2
				# Defensive bounds check to prevent IndexError (should not trigger due to initial check)
				if idx2 >= len(rx_buffer):
					log.warning(f"LED pattern buffer too short: need index {idx2}, have {len(rx_buffer)} bytes")
					led_processing_complete = False
					break
				v, valid = parse_hex_byte_pair(rx_buffer, idx1, idx2)
				if not valid:
					log.warning(f"Invalid hex at LED position {x}, aborting LED pattern")
					led_processing_complete = False
					break
				mpattern[x] = v
			# Only process and remove bytes from buffer if we successfully processed all LED values
			if not led_processing_complete:
				break  # Wait for more data
			rx_buffer = rx_buffer[required_bytes:]  # Remove L + 2 slot + 81*2 hex + 2 checksum
			
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
				board.ledArray(ledfields, speed=5, intensity=5, repeat=0)
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
		else:
			log.info(f"Handled command: {cmd}")

# Initialize BLE application
running = True
app = Application()
app.add_service(UARTService(0))

# Register the application first
try:
	app.register()
	log.info("BLE application registered successfully")
	
	# Query BlueZ to verify what properties are actually registered
	# This helps diagnose if BlueZ is adding security requirements
	try:
		from DGTCentaurMods.thirdparty.bletools import BleTools
		bus = BleTools.get_bus()
		
		# Get the ObjectManager to query registered objects
		om = dbus.Interface(
			bus.get_object("org.bluez", "/"),
			"org.freedesktop.DBus.ObjectManager")
		objects = om.GetManagedObjects()
		
		log.info("=" * 60)
		log.info("Querying BlueZ for registered characteristic properties...")
		log.info("=" * 60)
		
		# Find our characteristics in the registered objects
		for path, interfaces in objects.items():
			if "org.bluez.GattCharacteristic1" in interfaces:
				char_props = interfaces["org.bluez.GattCharacteristic1"]
				char_uuid = char_props.get("UUID", "unknown")
				char_flags = char_props.get("Flags", [])
				char_path = str(path)
				
				# Check if this is one of our characteristics
				if "49535343" in char_uuid:
					log.info(f"Found characteristic: {char_uuid}")
					log.info(f"  Path: {char_path}")
					log.info(f"  Flags reported by BlueZ: {char_flags}")
					
					# Check for security flags
					security_flags = [f for f in char_flags if any(sec in f.lower() for sec in ['encrypt', 'secure', 'authenticated', 'bond'])]
					if security_flags:
						log.warning(f"  ⚠ Security flags found: {security_flags}")
						log.warning(f"  ⚠ These flags may require bonding/encryption")
					else:
						log.info(f"  ✓ No security flags found (allows unbonded connections)")
					
					log.info("")
		
		log.info("=" * 60)
	except Exception as e:
		log.warning(f"Could not query BlueZ for characteristic properties: {e}")
		log.warning("This is not critical - characteristics should still work")
		import traceback
		log.debug(traceback.format_exc())
	
except Exception as e:
	log.error(f"Failed to register BLE application: {e}")
	import traceback
	log.error(traceback.format_exc())
	raise

# Register advertisement
adv = UARTAdvertisement(0)
try:
	adv.register()
	log.info("BLE advertisement registered successfully")
except Exception as e:
	log.error(f"Failed to register BLE advertisement: {e}")
	import traceback
	log.error(traceback.format_exc())

log.info("Millennium BLE service registered and advertising")
log.info("Waiting for BLE connection...")
log.info("To verify BLE advertisement is working, run: sudo hcitool lescan")
log.info("You should see 'MILLENNIUM CHESS' in the scan results")
log.info(f"Device MAC address: B8:27:EB:21:D2:51 (should be visible to ChessLink)")

# Subscribe to game manager
gamemanager.subscribeGame(eventCallback, moveCallback, keyCallback)
board.display_manager.add_widget(TextWidget(50, 20, 88, 100, "Place pieces in Starting Position", background=3, font_size=18))

def cleanup():
	"""Clean up BLE services, advertisements, and resources before exit."""
	global kill, app, adv, bluetooth_controller, pairThread, cleaned_up
	if cleaned_up:
		return
	cleaned_up = True
	try:
		log.info("Cleaning up Millennium BLE services...")
		kill = 1
		
		# Stop BLE notifications
		if UARTService.tx_obj is not None:
			try:
				UARTService.tx_obj.StopNotify()
				log.info("BLE notifications stopped")
			except Exception as e:
				log.debug(f"Error stopping notify: {e}")
		
		# Unregister BLE advertisement
		try:
			if 'adv' in globals() and adv is not None:
				bus = BleTools.get_bus()
				adapter = BleTools.find_adapter(bus)
				if adapter:
					ad_manager = dbus.Interface(
						bus.get_object("org.bluez", adapter),
						"org.bluez.LEAdvertisingManager1")
					ad_manager.UnregisterAdvertisement(adv.get_path())
					log.info("BLE advertisement unregistered")
		except Exception as e:
			log.debug(f"Error unregistering advertisement: {e}")
		
		# Unregister BLE application
		try:
			if 'app' in globals() and app is not None:
				bus = BleTools.get_bus()
				adapter = BleTools.find_adapter(bus)
				if adapter:
					service_manager = dbus.Interface(
						bus.get_object("org.bluez", adapter),
						"org.bluez.GattManager1")
					service_manager.UnregisterApplication(app.get_path())
					log.info("BLE application unregistered")
		except Exception as e:
			log.debug(f"Error unregistering application: {e}")
		
		# Stop Bluetooth controller pairing thread
		try:
			if 'bluetooth_controller' in globals() and bluetooth_controller is not None:
				bluetooth_controller.stop_pairing_thread()
				log.info("Bluetooth pairing thread stopped")
		except Exception as e:
			log.debug(f"Error stopping pairing thread: {e}")
		
		# Unsubscribe from game manager
		try:
			gamemanager.unsubscribeGame()
			log.info("Unsubscribed from game manager")
		except Exception as e:
			log.debug(f"Error unsubscribing from game manager: {e}")
		
		# Turn off LEDs
		try:
			board.ledsOff()
		except Exception as e:
			log.debug(f"Error turning off LEDs: {e}")
		
		log.info("Cleanup completed")
	except Exception as e:
		log.error(f"Error in cleanup: {e}")
		import traceback
		log.error(traceback.format_exc())

def signal_handler(signum, frame):
	"""Handle termination signals."""
	log.info(f"Received signal {signum}, cleaning up...")
	cleanup()
	try:
		if 'app' in globals() and app is not None:
			app.quit()
	except Exception:
		pass
	sys.exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def check_kill_flag():
	"""Periodically check kill flag and quit app if set"""
	global kill, app
	if kill:
		log.info("Kill flag set, cleaning up and quitting application")
		cleanup()
		try:
			app.quit()
		except Exception:
			pass
		return False  # Stop the timeout
	return True  # Continue checking

# Start periodic check for kill flag (every 100ms)
GObject.timeout_add(100, check_kill_flag)

# Main loop - run BLE application mainloop
try:
	app.run()
except KeyboardInterrupt:
	log.info("Keyboard interrupt received")
	running = False
except Exception as e:
	log.error(f"Error in main loop: {e}")
	import traceback
	log.error(traceback.format_exc())
	running = False

# Cleanup
log.info("Shutting down...")
running = False
cleanup()

# Give cleanup time to complete
time.sleep(0.5)

try:
	if 'app' in globals() and app is not None:
		app.quit()
except Exception:
	pass

log.info("Disconnected")
time.sleep(0.5)

log.info("Exiting millennium.py")

