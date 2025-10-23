#!/usr/bin/env python3

import sys

sys.path.insert(0, '.')

from DGTCentaurMods.board.async_centaur import AsyncCentaur, DGT_BUS_SEND_CHANGES

if __name__ == "__main__":
    print("Initializing AsyncCentaur...")
    asyncserial = AsyncCentaur(developer_mode=False)
    print("Waiting for AsyncCentaur initialization...")
    
    if asyncserial.wait_ready():
        
        try:
            asyncserial.ledsOff()
            asyncserial.sendPacket(DGT_BUS_SEND_CHANGES)
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
            print("Closing AsyncCentaur connection...")
            asyncserial.close()
            print("Done.")
    else:
        print("Failed to initialize AsyncCentaur")
        asyncserial.close()
