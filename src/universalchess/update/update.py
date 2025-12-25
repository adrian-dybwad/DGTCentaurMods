#!/usr/bin/python
# Display progess of DGTCentaurMods installation on first boot
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

import os
from universalchess.display.epaper_service import service, widgets
import os, time
import threading

global animate
global progress

service.init()
sb = widgets.status_bar()
sb.start()
sb.print()

def status():
    global animate
    global progress
    animate = True
    while animate:
        for a in ['/','-','\\','|']:
            widgets.write_text(1,progress + "[" + a + "]")
            time.sleep(1)


progress = 'Updating OS    '
msg = threading.Thread(target=status,args=())
msg.start()
time.sleep(0.5)
widgets.write_text(3,"[1/2] Updating")
widgets.write_text(4,"    Raspbian")
os.system("sudo apt update")
os.system("sudo apt full-upgrade -y")

progress = 'Updating       '
widgets.write_text(5,"[2/2] Updating")
widgets.write_text(6,"    DGTCM")
os.system("sudo apt install -y /tmp/dgtcentaurmods_armhf.deb")

animate = False
sb.stop()
time.sleep(3)
widgets.clear_screen()
time.sleep(1)
print('Setup dome')

widgets.write_text(3,'     Shutting')
widgets.write_text(4,'       down')
time.sleep(5)
service.shutdown()
os.system("sudo systemctl start universal-chess-stop-controller.service")
