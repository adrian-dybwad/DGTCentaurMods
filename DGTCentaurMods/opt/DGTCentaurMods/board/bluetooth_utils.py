"""Bluetooth utility functions for DGT Centaur Mods"""
import time
import select
import subprocess
import psutil
from typing import Optional, Callable
import pathlib
from DGTCentaurMods.board.logging import log

class BluetoothManager:
    """Manage Bluetooth pairing and discoverability"""
    
    PIN_CONF_PATHS = [
        "/etc/bluetooth/pin.conf",
        str(pathlib.Path(__file__).parent.parent.parent / "etc/bluetooth/pin.conf")
    ]
    
    @staticmethod
    def kill_bt_agent():
        """Kill any running bt-agent processes"""
        for p in psutil.process_iter(attrs=['pid', 'name']):
            if "bt-agent" in p.info["name"]:
                p.kill()
                time.sleep(1)
    
    @staticmethod
    def ensure_bluetooth_enabled():
        """Enable Bluetooth and make discoverable"""
        p = subprocess.Popen(
            ['/usr/bin/bluetoothctl'],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            universal_newlines=True,
            shell=True
        )
        p.stdin.write("power on\n")
        p.stdin.flush()
        p.stdin.write("discoverable on\n")
        p.stdin.flush()
        p.stdin.write("pairable on\n")
        p.stdin.flush()
        time.sleep(4)
        p.terminate()
    
    @staticmethod
    def get_pin_conf_path() -> Optional[str]:
        """Find pin.conf file in standard locations"""
        for path in BluetoothManager.PIN_CONF_PATHS:
            if pathlib.Path(path).exists():
                return path
        return None
    
    @classmethod
    def start_pairing(cls, timeout: int = 60, on_device_detected: Optional[Callable] = None) -> bool:
        """
        Start Bluetooth pairing mode
        
        Args:
            timeout: Seconds to wait for pairing (0 = infinite)
            on_device_detected: Optional callback when device detected
            
        Returns:
            True if device paired, False if timeout
        """
        cls.kill_bt_agent()
        cls.ensure_bluetooth_enabled()
        
        pin_conf = cls.get_pin_conf_path()
        if not pin_conf:
            log.warning("Warning: pin.conf not found, using NoInputNoOutput")
            cmd = '/usr/bin/bt-agent --capability=NoInputNoOutput'
        else:
            cmd = f'/usr/bin/bt-agent --capability=NoInputNoOutput -p {pin_conf}'
        
        p = subprocess.Popen(
            [cmd],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            shell=True
        )
        poll_obj = select.poll()
        poll_obj.register(p.stdout, select.POLLIN)
        
        start_time = time.time()
        running = True
        spamyes = False
        spamtime = 0
        
        while running:
            # Check timeout
            if timeout > 0 and time.time() - start_time > timeout:
                p.terminate()
                return False
            
            poll_result = poll_obj.poll(0)
            
            if spamyes:
                if time.time() - spamtime < 3:
                    p.stdin.write(b'yes\n')
                    time.sleep(1)
                else:
                    p.terminate()
                    return True
            
            if poll_result and not spamyes:
                line = p.stdout.readline()
                if b'Device:' in line:
                    log.info("Device detected, pairing...")
                    p.stdin.write(b'yes\n')
                    if on_device_detected:
                        on_device_detected()
                    spamyes = True
                    spamtime = time.time()
            
            r = p.poll()
            if r is not None:
                running = False
            
            time.sleep(0.1)
        
        return False
    
    @classmethod
    def start_pairing_thread(cls, timeout: int = 0):
        """Run pairing in background thread (for eboard/millennium modes)"""
        import threading
        
        def pair_loop():
            while True:
                cls.start_pairing(timeout=0)  # Run indefinitely
                time.sleep(0.1)
        
        thread = threading.Thread(target=pair_loop, daemon=True)
        thread.start()
        return thread
