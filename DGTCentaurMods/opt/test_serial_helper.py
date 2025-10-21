#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.serial_helper import SerialHelper

if __name__ == "__main__":
    print("Initializing SerialHelper...")
    helper = SerialHelper(developer_mode=False)
    print(f"Board addresses discovered: addr1={hex(helper.addr1)}, addr2={hex(helper.addr2)}")
    
    print("\nInitializing device...")
    helper.initialize_device()
    
    print("\nTest complete. Closing serial connection...")
    helper.close()
    print("Done.")
