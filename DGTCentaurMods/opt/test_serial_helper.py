#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.serial_helper import SerialHelper

if __name__ == "__main__":
    print("Initializing SerialHelper...")
    helper = SerialHelper(developer_mode=False)
    print("Waiting for initialization...")
    
    if helper.wait_ready():
        
        helper.ledsOff()
        helper.sendPacket(b'\x83', b'') #Piece detection enabled
        #helper.sendPacket(b'\x94', b'') #Key detection enabled
        print("\nListening for serial data (press Ctrl+C to stop)...")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            print("Closing serial connection...")
            helper.close()
            print("Done.")
    else:
        print("Failed to initialize SerialHelper")
        helper.close()
