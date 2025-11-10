# Mac VM Solution for Centaur Binary Development

This solution runs the Bullseye-compiled centaur binary in a VM on your Mac, connected to the real Raspberry Pi hardware via serial port relay and network.

## Overview

Instead of running the VM on the resource-constrained Pi, we run it on your Mac where there's plenty of CPU, RAM, and storage. The VM connects to the real Pi hardware via:

1. **Serial Port Relay**: Mac → Network/Serial → Pi `/dev/serial0`
2. **Display Access**: VM → Network → Pi e-paper display (via proxy daemon)
3. **Hardware Verification**: Test serial communications and hardware interactions

## Architecture

```
┌─────────────────────────────────────────┐
│  Mac (Development Machine)              │
│  ┌───────────────────────────────────┐ │
│  │  QEMU VM (Debian Bullseye ARM)    │ │
│  │  ┌───────────────────────────────┐ │ │
│  │  │  centaur binary                │ │ │
│  │  │  (Bullseye kernel compatible)  │ │ │
│  │  └───────────────────────────────┘ │ │
│  │  Serial: /dev/ttyUSB0 or network   │ │
│  └───────────────────────────────────┘ │
│         │                    │          │
│         │ Serial Relay       │ Network  │
│         ▼                    ▼          │
└─────────┼────────────────────┼──────────┘
          │                    │
          │                    │
┌─────────▼────────────────────▼──────────┐
│  Raspberry Pi (Hardware)                │
│  - /dev/serial0 (board communication)  │
│  - GPIO/SPI (e-paper display)          │
│  - Serial Relay Daemon                 │
│  - Display Proxy Daemon                 │
└─────────────────────────────────────────┘
```

## Requirements

### Mac Side:
- **macOS** with sufficient resources (8GB+ RAM recommended)
- **QEMU** installed (`brew install qemu`)
- **Serial port access** (USB-to-Serial adapter or network relay)
- **Network connection** to Raspberry Pi

### Pi Side:
- **Serial relay daemon** (receives serial data from Mac, forwards to `/dev/serial0`)
- **Display proxy daemon** (receives display commands from Mac, controls e-paper)
- **Network connectivity** to Mac

## Implementation Options

### Option 1: Serial Port Relay via Network (Recommended)

**Mac VM** → Network Socket → **Pi Serial Relay** → `/dev/serial0`

**Advantages:**
- Works over network (no physical USB cable needed)
- Flexible - can test from anywhere
- Easy to debug and monitor

**Implementation:**
1. Run serial relay daemon on Pi
2. VM connects to Pi's IP address
3. Relay forwards serial data bidirectionally

### Option 2: USB-to-Serial Direct Connection

**Mac VM** → USB Serial Device → **Pi** (via USB-to-Serial adapter)

**Advantages:**
- Direct hardware connection
- Lower latency
- Simpler setup

**Disadvantages:**
- Requires physical USB-to-Serial adapter
- Pi needs USB serial interface

### Option 3: SSH/Serial Tunnel

**Mac VM** → SSH Tunnel → **Pi** → `/dev/serial0`

**Advantages:**
- Uses existing SSH connection
- Secure
- No additional software needed

## Setup Instructions

### Step 1: Install QEMU on Mac

```bash
brew install qemu
```

### Step 2: Create Bullseye ARM VM Image

```bash
cd build/vm-mac
./setup-mac-vm.sh
```

This creates the VM disk image (8GB).

### Step 3: Install Debian Bullseye

**Option A: Use the helper script (Easiest)**
```bash
cd build/vm-mac
./install-debian.sh
```

This will:
- Download the Debian Bullseye ARM netinst ISO (if needed)
- Launch the Debian installer in the VM
- Guide you through installation

**Option B: Manual installation**
```bash
# Download ISO manually
cd ~/.dgtcentaurmods-vm
curl -L -o debian-11.9.0-armhf-netinst.iso \
  https://cdimage.debian.org/cdimage/archive/11.9.0/armhf/iso-cd/debian-11.9.0-armhf-netinst.iso

# Install Debian
qemu-system-arm -M virt -cpu cortex-a15 -m 2G \
  -drive file=bullseye-arm.img,format=qcow2 \
  -cdrom debian-11.9.0-armhf-netinst.iso \
  -boot d \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-device,netdev=net0 \
  -display none -nographic
```

**Installation Notes:**
- Follow the Debian installer prompts
- Select the virtio disk when partitioning
- Install minimal system (no desktop needed)
- After installation, SSH: `ssh -p 2222 root@localhost`

### Step 3: Set Up Serial Relay on Pi

The Pi needs a daemon that:
1. Listens on a network port
2. Forwards data to/from `/dev/serial0`
3. Handles reconnection

See `build/vm-mac/pi-serial-relay.py` for implementation.

### Step 4: Set Up Display Proxy on Pi

The Pi needs a daemon that:
1. Receives display commands from Mac VM
2. Controls GPIO/SPI for e-paper display
3. Provides display status

See `build/vm-mac/pi-display-proxy.py` for implementation.

### Step 5: Launch VM with Serial Connection

```bash
cd build/vm-mac
./run-centaur-vm.sh --pi-ip 192.168.1.100
```

## Serial Relay Implementation

### Pi Side: Serial Relay Daemon

The relay daemon runs on the Pi and:
- Listens on TCP port (e.g., 8888)
- Forwards data between network socket and `/dev/serial0`
- Handles connection drops gracefully
- Logs all traffic for debugging

### Mac VM Side: Serial Connection

The VM connects to the relay via:
- Network socket to Pi's IP:port
- Virtual serial device in VM
- QEMU serial chardev with socket backend

## Display Proxy Implementation

### Option A: Network API

Pi runs a simple HTTP/WebSocket server that:
- Receives display commands (update screen, clear, etc.)
- Executes GPIO/SPI operations
- Returns status

VM connects via HTTP/WebSocket client.

### Option B: Shared Memory/Unix Socket

More complex but lower latency:
- Pi creates shared memory segment
- VM accesses via network filesystem
- Requires more setup

### Option C: Display Emulator (No Real Hardware)

For serial communication testing only:
- Run centaur binary in VM
- Emulate display in software
- Test serial communications without display hardware

## Benefits of This Approach

1. **Full Kernel Compatibility**: VM runs Bullseye kernel - binary works perfectly
2. **Hardware Access**: Real Pi hardware via network relay
3. **Development Friendly**: Debug on Mac with full tools
4. **Resource Abundant**: Mac has plenty of CPU/RAM
5. **Serial Debugging**: Easy to monitor and log serial traffic
6. **Flexible**: Can test different scenarios easily

## Use Cases

1. **Serial Communication Investigation**: 
   - Monitor all serial traffic
   - Test different protocols
   - Debug communication issues

2. **Hardware Verification**:
   - Test against real hardware
   - Verify board communication
   - Validate display functionality

3. **Development**:
   - Develop and test without touching Pi
   - Use Mac development tools
   - Faster iteration cycle

## Limitations

1. **Network Latency**: Serial relay adds some latency (usually <10ms)
2. **Display Complexity**: Display proxy adds complexity
3. **Setup Complexity**: More moving parts than native execution
4. **Network Dependency**: Requires stable network connection

## Quick Start

```bash
# On Mac
cd build/vm-mac
./setup-mac-vm.sh
./run-centaur-vm.sh --pi-ip <PI_IP_ADDRESS>

# On Pi (in separate terminal)
cd build/vm-mac
python3 pi-serial-relay.py
python3 pi-display-proxy.py
```

## Next Steps

1. Create Mac VM setup script
2. Create serial relay daemon for Pi
3. Create display proxy daemon for Pi
4. Create VM launch script with networking
5. Test serial communication
6. Test display functionality

