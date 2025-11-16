#!/usr/bin/env python3
"""
Epaper Proxy Wrapper
Wraps centaur execution to inject epaper proxy driver without modifying centaur code.
Uses Python import path manipulation to replace epaperDriver module.
"""

import sys
import os
import subprocess
import argparse
import socket
import struct
import time
from PIL import Image

PROXY_PORT = 8889
server_socket = None

class EpaperProxyDriver:
    """Proxy epaper driver that forwards to server"""
    
    instance = None
    
    def __new__(cls):
        if cls.instance is None:
            cls.instance = super(EpaperProxyDriver, cls).__new__(cls)
            cls.instance._connected = False
            cls.instance._server_ip = None
            cls.instance._server_port = PROXY_PORT
        return cls.instance
    
    def _connect(self):
        """Connect to epaper proxy server"""
        if self._connected and server_socket:
            return True
        
        if not self._server_ip:
            return False
        
        global server_socket
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.connect((self._server_ip, self._server_port))
            self._connected = True
            print(f"Connected to epaper proxy server at {self._server_ip}:{self._server_port}")
            return True
        except Exception as e:
            print(f"Failed to connect to epaper proxy server: {e}")
            self._connected = False
            return False
    
    def _send_display_update(self, image):
        """Send display update to server"""
        if not self._connect():
            return
        
        try:
            width, height = image.size
            mode = image.mode
            image_bytes = image.tobytes()
            
            mode_bytes = mode.encode('utf-8')
            mode_len = len(mode_bytes)
            
            data = struct.pack('!II', width, height)
            data += struct.pack('!I', mode_len)
            data += mode_bytes
            data += image_bytes
            
            size_header = struct.pack('!I', len(data))
            server_socket.sendall(size_header + data)
        except Exception as e:
            print(f"Error sending display update: {e}")
            self._connected = False
    
    def getbuffer(self, image):
        """Convert image to buffer format and send to server"""
        # Send full image update
        self._send_display_update(image)
        
        # Return buffer in expected format (same as real driver)
        buf = [0xFF] * (int(128 / 8) * 296)
        image_monocolor = image.convert('1')
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        if(imwidth == 128 and imheight == 296):
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * 128) / 8)] &= ~(0x80 >> (x % 8))
        elif(imwidth == 296 and imheight == 128):
            for y in range(imheight):
                for x in range(imwidth):
                    newx = y
                    newy = 296 - x - 1
                    if pixels[x, y] == 0:
                        buf[int((newx + newy * 128) / 8)] &= ~(0x80 >> (y % 8))
        else:
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * 128) / 8)] &= ~(0x80 >> (x % 8))
        return bytes(buf)
    
    def init(self):
        """Initialize display (no-op for proxy)"""
        self._connect()
    
    def reset(self):
        """Reset display (no-op for proxy)"""
        pass
    
    def clear(self):
        """Clear display"""
        # Send blank white image
        blank = Image.new('1', (128, 296), 255)
        self._send_display_update(blank)
    
    def display(self, bitmap):
        """Display bitmap"""
        # Convert bitmap bytes back to image
        # Bitmap format: 128/8 * 296 = 4736 bytes
        if isinstance(bitmap, bytes) and len(bitmap) == 4736:
            image = Image.new('1', (128, 296), 255)
            pixels = image.load()
            for y in range(296):
                for x in range(128):
                    byte_idx = int((x + y * 128) / 8)
                    bit_idx = x % 8
                    if byte_idx < len(bitmap):
                        if (bitmap[byte_idx] & (0x80 >> bit_idx)) == 0:
                            pixels[x, y] = 0
            self._send_display_update(image)
    
    def DisplayPartial(self, image):
        """Display partial update"""
        if isinstance(image, Image.Image):
            self._send_display_update(image)
        else:
            self.display(image)
    
    def DisplayRegion(self, y_start, y_end, image):
        """Display region update"""
        if isinstance(image, Image.Image):
            self._send_display_update(image)
        else:
            self.display(image)
    
    def sleepDisplay(self):
        """Sleep display (no-op for proxy)"""
        pass
    
    def openDisplay(self):
        """Open display (no-op for proxy)"""
        self._connect()

def create_proxy_module(server_ip):
    """Create a proxy epaper_driver module that will be imported instead of the real one"""
    
    # Create temporary directory structure matching DGTCentaurMods.display.epaper_driver
    proxy_dir = "/tmp/epaper_proxy_module"
    display_dir = f"{proxy_dir}/DGTCentaurMods/display"
    os.makedirs(display_dir, exist_ok=True)
    
    # Create __init__.py files
    with open(f"{proxy_dir}/__init__.py", "w") as f:
        f.write("# Epaper proxy module\n")
    with open(f"{proxy_dir}/DGTCentaurMods/__init__.py", "w") as f:
        f.write("# DGTCentaurMods proxy\n")
    with open(f"{display_dir}/__init__.py", "w") as f:
        f.write("# Display proxy\n")
    
    # Create epaper_driver.py that uses our proxy
    # Embed the proxy driver class directly to avoid import issues
    proxy_code = f'''"""
Epaper Driver Proxy Module
Automatically injected to replace real epaper driver.
"""
import socket
import struct
from PIL import Image

PROXY_PORT = 8889
_server_socket = None
_server_ip = "{server_ip}"

class EpaperProxyDriver:
    """Proxy epaper driver that forwards to server"""
    
    instance = None
    
    def __new__(cls):
        if cls.instance is None:
            cls.instance = super(EpaperProxyDriver, cls).__new__(cls)
            cls.instance._connected = False
        return cls.instance
    
    def _connect(self):
        """Connect to epaper proxy server"""
        global _server_socket
        if self._connected and _server_socket:
            return True
        
        try:
            _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _server_socket.connect((_server_ip, PROXY_PORT))
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            return False
    
    def _send_display_update(self, image):
        """Send display update to server"""
        if not self._connect():
            return
        
        global _server_socket
        try:
            width, height = image.size
            mode = image.mode
            image_bytes = image.tobytes()
            mode_bytes = mode.encode('utf-8')
            mode_len = len(mode_bytes)
            
            data = struct.pack('!II', width, height)
            data += struct.pack('!I', mode_len)
            data += mode_bytes
            data += image_bytes
            
            size_header = struct.pack('!I', len(data))
            _server_socket.sendall(size_header + data)
        except Exception:
            self._connected = False
    
    def getbuffer(self, image):
        """Convert image to buffer format and send to server"""
        self._send_display_update(image)
        buf = [0xFF] * (int(128 / 8) * 296)
        image_monocolor = image.convert('1')
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        if(imwidth == 128 and imheight == 296):
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * 128) / 8)] &= ~(0x80 >> (x % 8))
        elif(imwidth == 296 and imheight == 128):
            for y in range(imheight):
                for x in range(imwidth):
                    newx = y
                    newy = 296 - x - 1
                    if pixels[x, y] == 0:
                        buf[int((newx + newy * 128) / 8)] &= ~(0x80 >> (y % 8))
        else:
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * 128) / 8)] &= ~(0x80 >> (x % 8))
        return bytes(buf)
    
    def init(self):
        self._connect()
    
    def reset(self):
        pass
    
    def clear(self):
        blank = Image.new('1', (128, 296), 255)
        self._send_display_update(blank)
    
    def display(self, bitmap):
        if isinstance(bitmap, bytes) and len(bitmap) == 4736:
            image = Image.new('1', (128, 296), 255)
            pixels = image.load()
            for y in range(296):
                for x in range(128):
                    byte_idx = int((x + y * 128) / 8)
                    bit_idx = x % 8
                    if byte_idx < len(bitmap):
                        if (bitmap[byte_idx] & (0x80 >> bit_idx)) == 0:
                            pixels[x, y] = 0
            self._send_display_update(image)
    
    def DisplayPartial(self, image):
        if isinstance(image, Image.Image):
            self._send_display_update(image)
        else:
            self.display(image)
    
    def DisplayRegion(self, y_start, y_end, image):
        if isinstance(image, Image.Image):
            self._send_display_update(image)
        else:
            self.display(image)
    
    def sleepDisplay(self):
        pass
    
    def openDisplay(self):
        self._connect()

# Export as epaperDriver (matching original module name)
epaperDriver = EpaperProxyDriver
'''
    
    with open(f"{display_dir}/epaper_driver.py", "w") as f:
        f.write(proxy_code)
    
    return proxy_dir

def main():
    parser = argparse.ArgumentParser(description='Run centaur with epaper proxy (no code modification required)')
    parser.add_argument('--server-ip', required=True, help='IP address of Pi running epaper proxy server')
    parser.add_argument('--centaur-path', default='/home/pi/centaur/centaur', 
                       help='Path to centaur executable (default: /home/pi/centaur/centaur)')
    parser.add_argument('--centaur-args', nargs=argparse.REMAINDER, 
                       help='Additional arguments to pass to centaur')
    args = parser.parse_args()
    
    # Check if centaur is a Python script or binary
    centaur_path = args.centaur_path
    if not os.path.exists(centaur_path):
        print(f"Error: Centaur executable not found at {centaur_path}")
        return 1
    
    # Create proxy module
    print("Setting up epaper proxy...")
    proxy_dir = create_proxy_module(args.server_ip)
    
    # Add proxy directory to Python path (will be imported first)
    sys.path.insert(0, proxy_dir)
    
    # Check if centaur is a Python script
    is_python = False
    try:
        with open(centaur_path, 'rb') as f:
            first_line = f.readline()
            if first_line.startswith(b'#!'):
                shebang = first_line.decode('utf-8', errors='ignore')
                if 'python' in shebang.lower():
                    is_python = True
    except:
        pass
    
    # Set environment variable for Python scripts
    os.environ['PYTHONPATH'] = f"{proxy_dir}:{os.environ.get('PYTHONPATH', '')}"
    
    if is_python:
        print("Detected Python script, using PYTHONPATH injection")
        # Run as Python script with our path
        cmd = [sys.executable, centaur_path] + (args.centaur_args or [])
    else:
        print("Detected binary, attempting LD_PRELOAD approach")
        print("Note: Binary executables may not support epaper proxying without modification")
        # For binaries, we can't easily intercept - just run it
        # The serial relay will still work
        cmd = [centaur_path] + (args.centaur_args or [])
        if os.path.exists(centaur_path) and not os.access(centaur_path, os.X_OK):
            cmd = ['sudo'] + cmd
    
    print(f"Starting centaur: {' '.join(cmd)}")
    print("Epaper updates will be forwarded to Pi")
    
    try:
        result = subprocess.run(cmd)
        return result.returncode
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    finally:
        # Cleanup
        global server_socket
        if server_socket:
            server_socket.close()

if __name__ == "__main__":
    sys.exit(main())

