#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.async_serial import AsyncSerial as async_serial

if __name__ == "__main__":
    print("Initializing AsyncSerial...")
    asyncserial = async_serial(developer_mode=False)
    print("Waiting for AsyncSerial initialization...")
    
    if asyncserial.wait_ready():
        
        try:
            asyncserial.ledsOff()
            asyncserial.sendPacket(async_serial.PIECE_POLL_CMD, b'') #Piece detection enabled
            asyncserial.ledsOff()
        except Exception as e:
            print(f"Error: {e}")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            print("Closing AsyncSerial connection...")
            asyncserial.close()
            print("Done.")
    else:
        print("Failed to initialize AsyncSerial")
        asyncserial.close()
