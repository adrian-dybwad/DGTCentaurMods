#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.serial_helper import SerialHelper, PIECE_POLL_CMD, KEY_POLL_CMD

if __name__ == "__main__":
    print("Initializing SerialHelper...")
    helper = SerialHelper(developer_mode=False)
    print("Waiting for initialization...")
    
    if helper.wait_ready():
        
        try:
            helper.ledsOff()
            helper.sendPacket(PIECE_POLL_CMD, b'') #Piece detection enabled
            helper.ledsOff()
        except Exception as e:
            print(f"Error: {e}")
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
