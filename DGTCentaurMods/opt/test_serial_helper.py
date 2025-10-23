#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.async_centaur import AsyncCentaur, PIECE_POLL_CMD

if __name__ == "__main__":
    print("Initializing AsyncSerial...")
    asyncserial = AsyncCentaur(developer_mode=False)
    print("Waiting for AsyncSerial initialization...")
    
    if centaur.wait_ready():
        
        try:    
            centaur.ledsOff()
            centaur.sendPacket(PIECE_POLL_CMD, b'') #Piece detection enabled
            centaur.ledsOff()
            
            print(centaur.wait_for_key_up())
            print(centaur.wait_for_key_up())
            print(centaur.wait_for_key_up(accept='TICK'))

            code, name = centaur.wait_for_key_up(accept='PLAY')
            print(name)
            #Or in one line (with None-safe fallback):
            print((centaur.wait_for_key_up(accept='BACK') or (None, None))[1])

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
