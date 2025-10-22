#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.async_serial import AsyncSerial, PIECE_POLL_CMD

if __name__ == "__main__":
    print("Initializing AsyncSerial...")
    asyncserial = AsyncSerial(developer_mode=False)
    print("Waiting for AsyncSerial initialization...")
    
    if asyncserial.wait_ready():
        
        try:
            asyncserial.ledsOff()
            asyncserial.sendPacket(PIECE_POLL_CMD, b'') #Piece detection enabled
            asyncserial.ledsOff()
            
            print(asyncserial.wait_for_key_up())
            print(asyncserial.wait_for_key_up())
            print(asyncserial.wait_for_key_up(accept='TICK'))

            code, name = asyncserial.wait_for_key_up(accept='PLAY')
            print(name)
            #Or in one line (with None-safe fallback):
            print((asyncserial.wait_for_key_up(accept='BACK') or (None, None))[1])


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
