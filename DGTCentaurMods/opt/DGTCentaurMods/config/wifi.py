# Connect to a Wifi Network
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

from DGTCentaurMods.board import board
import os
import time
import sys
import re

board.initScreen()
time.sleep(2)

command = """sudo iwlist wlan0 scan | grep 'ESSID'"""
result = os.popen(command)

# Extract ESSID names using regex
essids = re.findall(r'ESSID:"(.*?)"', result.read())

# Remove empty and duplicate entries
unique_essids = sorted(set(filter(None, essids)))

networks = {ssid: ssid for ssid in unique_essids}
print("----------------------------------------------------------")
print(networks)
print("----------------------------------------------------------")
answer = board.doMenu(networks,1)
print("++++++++++++++++++++++++++++++")
print(answer)
print("++++++++++++++++++++++++++++++")

if answer == "BACK":
	sys.exit()

#board.initScreen()
#time.sleep(2)
board.epd.init()

# If the answer is not "BACK" then answer contains our SSID
# Now we need to get the password
password = board.getText("Wifi Password")

if password == "":
	sys.exit()

# Add an SSID
cmd = """sudo sh -c \"wpa_passphrase '""" + answer + """' '""" + password + """'\""""
res = os.popen(cmd)
result = list(res)
section = ""
for i in range(0,len(result)):
	section = section + result[i]
print(section)
if section.find("ssid") != -1:
	wpas = open('/etc/wpa_supplicant/wpa_supplicant.conf','r')
	curconf = wpas.read()
	wpas.close()
	print(curconf)
	if curconf.find(answer) != -1:
		# SSID is already in file
		newtext = re.sub(r'network={[^\}]+?ssid=\"' + answer + r'\"[^\}]+?\}\n','',curconf,re.DOTALL)
		print(newtext)
		wpas = open('/etc/wpa_supplicant/wpa_supplicant.conf','w')
		wpas.write(newtext)
		wpas.close()
	# Success - append it to wpa_supplicant
	wpas = open('/etc/wpa_supplicant/wpa_supplicant.conf','a')
	wpas.write(section)
	wpas.close()
	os.system("sudo wpa_cli -i wlan0 reconfigure")
