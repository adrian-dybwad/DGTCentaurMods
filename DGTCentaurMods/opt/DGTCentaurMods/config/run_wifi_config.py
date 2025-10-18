#!/usr/bin/env python3
"""
Simple script to run standalone WiFi configuration.
This bypasses the main menu system to avoid display conflicts.
"""
import sys
import os
import subprocess

def main():
    print("🔧 DGT Centaur WiFi Configuration")
    print("=" * 40)
    
    # First, clean up any interfering processes
    print("🧹 Cleaning up interfering processes...")
    try:
        result = subprocess.run(['python3', '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/config/cleanup_dgt.py'], 
                              capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print("Warnings:", result.stderr)
    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")
    
    # Run the standalone WiFi configuration
    print("\n📡 Starting WiFi configuration...")
    try:
        script_path = '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/config/standalone_wifi.py'
        os.system(f'python3 {script_path}')
    except Exception as e:
        print(f"❌ Error running WiFi configuration: {e}")
        return 1
    
    print("\n✅ WiFi configuration completed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())

