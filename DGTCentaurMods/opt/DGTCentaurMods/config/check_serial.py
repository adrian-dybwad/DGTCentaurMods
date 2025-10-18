#!/usr/bin/env python3
"""
Check if serial port is available and provide guidance for fixing serial port issues.
"""
import subprocess
import sys
import os

def check_serial_port():
    """Check if /dev/serial0 is being used by another process"""
    try:
        # Check what processes are using the serial port
        result = subprocess.run(['lsof', '/dev/serial0'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            print("❌ Serial port /dev/serial0 is being used by:")
            print(result.stdout)
            return False
        else:
            print("✅ Serial port /dev/serial0 is available")
            return True
    except FileNotFoundError:
        print("⚠️  lsof command not found, trying alternative method...")
        try:
            # Alternative: check if we can open the port
            import serial
            ser = serial.Serial('/dev/serial0', 1000000, timeout=1)
            ser.close()
            print("✅ Serial port /dev/serial0 is available")
            return True
        except Exception as e:
            print(f"❌ Cannot access serial port: {e}")
            return False

def check_dgt_processes():
    """Check if DGT Centaur processes are running"""
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        dgt_processes = []
        for line in lines:
            if 'DGTCentaurMods' in line or 'menu.py' in line or 'board.py' in line:
                dgt_processes.append(line.strip())
        
        if dgt_processes:
            print("⚠️  Found running DGT Centaur processes:")
            for proc in dgt_processes:
                print(f"  {proc}")
            return True
        else:
            print("✅ No DGT Centaur processes running")
            return False
    except Exception as e:
        print(f"Error checking processes: {e}")
        return False

def main():
    print("🔍 Checking serial port availability...")
    print("=" * 50)
    
    serial_available = check_serial_port()
    processes_running = check_dgt_processes()
    
    print("\n" + "=" * 50)
    if not serial_available or processes_running:
        print("🚨 ISSUES FOUND:")
        if not serial_available:
            print("  - Serial port is locked by another process")
        if processes_running:
            print("  - DGT Centaur processes are still running")
        
        print("\n💡 SOLUTIONS:")
        print("  1. Kill any running DGT Centaur processes:")
        print("     sudo pkill -f DGTCentaurMods")
        print("     sudo pkill -f menu.py")
        print("     sudo pkill -f board.py")
        print("\n  2. If that doesn't work, restart the system:")
        print("     sudo reboot")
        print("\n  3. Or manually kill the process using the serial port:")
        print("     sudo lsof /dev/serial0")
        print("     sudo kill -9 <PID>")
    else:
        print("✅ All checks passed! Serial port should work properly.")
        print("\n🎯 You can now run the WiFi configuration:")
        print("   python3 wifi.py")

if __name__ == "__main__":
    main()

