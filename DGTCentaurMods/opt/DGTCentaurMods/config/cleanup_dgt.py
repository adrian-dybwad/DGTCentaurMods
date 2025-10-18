#!/usr/bin/env python3
"""
Kill any interfering DGT processes before running WiFi configuration.
"""
import subprocess
import sys
import time

def kill_dgt_processes():
    """Kill any running DGT Centaur processes"""
    print("🔍 Checking for running DGT processes...")
    
    try:
        # Get list of processes
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        
        dgt_processes = []
        for line in lines:
            if any(keyword in line for keyword in ['DGTCentaurMods', 'menu.py', 'board.py', 'epaper']):
                if 'python' in line or 'python3' in line:
                    parts = line.split()
                    if len(parts) > 1:
                        pid = parts[1]
                        dgt_processes.append((pid, line.strip()))
        
        if dgt_processes:
            print(f"⚠️  Found {len(dgt_processes)} DGT processes:")
            for pid, cmd in dgt_processes:
                print(f"  PID {pid}: {cmd}")
            
            print("\n🛑 Killing DGT processes...")
            for pid, cmd in dgt_processes:
                try:
                    subprocess.run(['kill', '-9', pid], check=True)
                    print(f"  ✅ Killed PID {pid}")
                except subprocess.CalledProcessError:
                    print(f"  ❌ Failed to kill PID {pid}")
            
            # Wait a moment for processes to die
            time.sleep(1)
            print("✅ DGT processes killed")
        else:
            print("✅ No DGT processes running")
            
    except Exception as e:
        print(f"❌ Error checking processes: {e}")

def check_serial_port():
    """Check if serial port is free"""
    try:
        result = subprocess.run(['lsof', '/dev/serial0'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            print("❌ Serial port still in use:")
            print(result.stdout)
            return False
        else:
            print("✅ Serial port is free")
            return True
    except FileNotFoundError:
        print("⚠️  lsof not available, assuming port is free")
        return True

def main():
    print("🧹 Cleaning up DGT processes...")
    print("=" * 40)
    
    kill_dgt_processes()
    
    print("\n🔍 Checking serial port...")
    if check_serial_port():
        print("\n✅ System is ready for WiFi configuration!")
        print("🎯 You can now run:")
        print("   python3 standalone_wifi.py")
    else:
        print("\n❌ Serial port still locked. Try:")
        print("   sudo reboot")

if __name__ == "__main__":
    main()

