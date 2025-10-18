#!/usr/bin/env python3
"""
Simple script to test key detection on the DGT Centaur board.
"""
import sys
import time
import signal

# Add the DGTCentaurMods path
sys.path.insert(0, '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')

shutdown_requested = False

def signal_handler(signum, frame):
    global shutdown_requested
    print("\n🛑 Shutdown requested...")
    shutdown_requested = True
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def test_key_detection():
    """Test key detection with detailed debugging"""
    try:
        from DGTCentaurMods.board import board as b
        print(f"✅ Board connected: {b.addr1:02x}:{b.addr2:02x}")
    except Exception as e:
        print(f"❌ Board connection failed: {e}")
        return
    
    print("🔍 Testing key detection...")
    print("Press any key on the board (or CTRL+C to exit)")
    
    attempt = 0
    while not shutdown_requested:
        attempt += 1
        try:
            # Clear buffer
            try:
                b._ser_read(1000)
            except:
                pass
            
            # Send key event request
            b.sendPacket(b'\x94', b'')
            resp = b._ser_read(256)
            
            if resp:
                hx = resp.hex()
                print(f"Attempt {attempt}: Response: {hx}")
                
                a1 = f"{b.addr1:02x}"
                a2 = f"{b.addr2:02x}"
                
                # Look for key event patterns
                if f"b100{a1}0{a2}" in hx:
                    key_code = hx[-2:]
                    key_name = "UNKNOWN"
                    
                    if key_code == "0d":
                        key_name = "SELECT"
                    elif key_code == "3c":
                        key_name = "UP"
                    elif key_code == "61":
                        key_name = "DOWN"
                    elif key_code == "47":
                        key_name = "BACK"
                    elif key_code == "6d":
                        key_name = "HELP"
                    elif key_code == "2a":
                        key_name = "PLAY"
                    
                    print(f"🎯 KEY DETECTED: {key_name} (code: {key_code})")
                else:
                    print(f"  No key event in response")
            else:
                print(f"Attempt {attempt}: No response")
            
        except Exception as e:
            print(f"Attempt {attempt}: Error: {e}")
        
        time.sleep(0.2)

if __name__ == "__main__":
    try:
        test_key_detection()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("👋 Goodbye!")
