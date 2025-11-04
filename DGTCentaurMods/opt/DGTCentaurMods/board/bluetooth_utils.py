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
    def _safe_terminate(p):
        """
        Safely terminate a subprocess by closing pipes before termination.
        
        Args:
            p: subprocess.Popen object to terminate
        """
        try:
            # Close stdin if it exists and isn't already closed
            if p.stdin and not p.stdin.closed:
                try:
                    p.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            
            # Close stdout if it exists and isn't already closed
            if p.stdout and not p.stdout.closed:
                try:
                    p.stdout.close()
                except (BrokenPipeError, OSError):
                    pass
            
            # Terminate the process
            p.terminate()
            
            # Wait for process to exit (with timeout)
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't terminate gracefully
                try:
                    p.kill()
                    p.wait(timeout=1)
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    pass
        except (ProcessLookupError, ValueError):
            # Process already terminated or invalid
            pass
    
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
        BluetoothManager._safe_terminate(p)
    
    @staticmethod
    def keep_discoverable(device_name: str = "MILLENNIUM CHESS"):
        """
        Keep Bluetooth device discoverable and set device name.
        This is needed for applications like Hiarcs to find the service after pairing.
        
        Args:
            device_name: Name to set for the Bluetooth device
        """
        try:
            p = subprocess.Popen(
                ['/usr/bin/bluetoothctl'],
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                shell=True
            )
            p.stdin.write("power on\n")
            p.stdin.flush()
            p.stdin.write(f"system-alias {device_name}\n")
            p.stdin.flush()
            # Use discoverable on with timeout 0 for indefinite discoverability
            # This ensures iPhone can discover the device throughout the pairing window
            p.stdin.write("discoverable on\n")
            p.stdin.flush()
            p.stdin.write("pairable on\n")
            p.stdin.flush()
            time.sleep(2)
            BluetoothManager._safe_terminate(p)
        except Exception as e:
            log.debug(f"Error keeping Bluetooth discoverable: {e}")
    
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
                cls._safe_terminate(p)
                return False
            
            poll_result = poll_obj.poll(0)
            
            if spamyes:
                if time.time() - spamtime < 3:
                    p.stdin.write(b'yes\n')
                    time.sleep(1)
                else:
                    # Pairing succeeded - don't terminate bt-agent, let it keep running
                    # The RFCOMM connection needs bt-agent to stay active
                    log.info("Pairing completed successfully, bt-agent will remain running")
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
            # Small delay to ensure bt-agent has started from start_pairing() before
            # we call keep_discoverable(). This prevents bluetoothctl commands from
            # interfering with bt-agent's initial pairing setup
            time.sleep(2.5)
            
            # Keep device discoverable from the start, not just after pairing
            # This ensures Android devices can discover the service during scanning
            cls.keep_discoverable("MILLENNIUM CHESS")
            last_discoverable_check = time.time()
            
            while True:
                paired = cls.start_pairing(timeout=0)  # Run indefinitely
                if paired:
                    # Pairing succeeded - bt-agent is still running
                    # Check periodically if it's still running, only restart if it exits
                    # Also keep device discoverable so applications like Hiarcs can find it
                    log.info("Pairing succeeded, monitoring bt-agent status and keeping discoverable")
                    # Set discoverable immediately after pairing
                    cls.keep_discoverable("MILLENNIUM CHESS")
                    last_discoverable_check = time.time()
                    while True:
                        time.sleep(10)  # Check every 10 seconds
                        # Keep device discoverable every 30 seconds
                        current_time = time.time()
                        if current_time - last_discoverable_check > 30:
                            cls.keep_discoverable("MILLENNIUM CHESS")
                            last_discoverable_check = current_time
                        
                        bt_agent_running = False
                        for p in psutil.process_iter(attrs=['pid', 'name']):
                            if "bt-agent" in p.info["name"]:
                                bt_agent_running = True
                                break
                        if not bt_agent_running:
                            log.info("bt-agent exited, restarting pairing")
                            break
                else:
                    # Pairing failed or timed out - restart quickly
                    # Keep device discoverable during retry
                    current_time = time.time()
                    if current_time - last_discoverable_check > 30:
                        cls.keep_discoverable("MILLENNIUM CHESS")
                        last_discoverable_check = current_time
                time.sleep(0.1)
        
        thread = threading.Thread(target=pair_loop, daemon=True)
        thread.start()
        return thread
