# Docker Container for Bullseye Centaur Binary

This Docker solution allows running the Bullseye-compiled centaur binary on Debian Trixie by containerizing it with Bullseye's compatible libraries and kernel interfaces.

## Overview

The original DGT Centaur binary was compiled for Debian Bullseye and is incompatible with Trixie's dynamic linker. This Docker container provides a Bullseye environment where the binary can run successfully.

## Requirements

- Docker installed on the Trixie system
- Docker daemon running
- Hardware access permissions (serial port, GPIO, SPI)

## Installation

### 1. Install Docker (if not already installed)

```bash
sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker pi
```

**Note**: You may need to log out and back in for the docker group membership to take effect.

### 2. Build the Docker Image

From the project root:

```bash
cd build/docker
./build-centaur-container.sh
```

Or manually:

```bash
docker build -t dgtcentaurmods/centaur-bullseye:latest build/docker/centaur-bullseye/
```

## Usage

The Docker container is automatically used when selecting "Centaur" from the DGTCentaurMods menu. The menu system will:

1. Check if Docker is available
2. Check if the Docker image exists (build if missing)
3. Launch the centaur binary in the container with full hardware access

### Manual Execution

To run the centaur binary manually in Docker:

```bash
sudo docker run --rm \
  --privileged \
  --device=/dev/serial0 \
  --device=/dev/gpiomem \
  --device=/dev/spidev0.0 \
  --device=/dev/spidev0.1 \
  -v /home/pi/centaur:/centaur:ro \
  -v /sys/class/gpio:/sys/class/gpio:ro \
  -w /centaur \
  dgtcentaurmods/centaur-bullseye:latest \
  /centaur/centaur
```

To check the exit code:
```bash
sudo docker run --rm \
  --privileged \
  --device=/dev/serial0 \
  --device=/dev/gpiomem \
  --device=/dev/spidev0.0 \
  --device=/dev/spidev0.1 \
  -v /home/pi/centaur:/centaur:ro \
  -v /sys/class/gpio:/sys/class/gpio:ro \
  -w /centaur \
  dgtcentaurmods/centaur-bullseye:latest
echo "Exit code: $?"
```

**Note**: The entire `/home/pi/centaur` directory is mounted (not just the binary) because the centaur executable requires access to libraries, configuration files, and other resources in that directory.

## Hardware Access

The container requires access to:

- **Serial Port** (`/dev/serial0`): For board communication
- **GPIO** (`/dev/gpiomem`, `/sys/class/gpio`): For e-paper display control
- **SPI Devices** (`/dev/spidev0.0`, `/dev/spidev0.1`): For e-paper display communication

The `--privileged` flag grants full hardware access. This is necessary for GPIO and SPI operations.

## Container Details

- **Base Image**: `arm32v7/debian:bullseye`
- **Architecture**: ARMv7 (compatible with Raspberry Pi)
- **Size**: Minimal (~50-100MB)
- **Lifetime**: Ephemeral (auto-removed on exit via `--rm`)

## Troubleshooting

### Docker Not Found

**Error**: "Docker is not installed"

**Solution**: Install Docker as described in the Installation section.

### Docker Daemon Not Running

**Error**: "Docker daemon is not running"

**Solution**:
```bash
sudo systemctl start docker
sudo systemctl enable docker  # To start on boot
```

### Permission Denied

**Error**: "permission denied while trying to connect to the Docker daemon socket"

**Solution**: Add your user to the docker group:
```bash
sudo usermod -aG docker pi
# Log out and back in, or:
newgrp docker
```

### Image Build Fails

**Error**: Docker build fails

**Solution**:
- Check internet connection (needs to download Bullseye base image)
- Ensure sufficient disk space
- Check Docker daemon logs: `sudo journalctl -u docker`

### Container Can't Access Hardware

**Error**: Serial port or GPIO not accessible in container

**Solution**:
- Ensure `--privileged` flag is used
- Verify devices exist: `ls -l /dev/serial0 /dev/gpiomem /dev/spidev0.*`
- Check permissions on host devices

### Centaur Still Segfaults in Container

**Error**: Segmentation fault (exit code 139) even in Docker

**Possible Causes**:
1. Binary is corrupted or wrong version
2. Missing libraries in container
3. Kernel interface incompatibility (container uses host kernel, not Bullseye kernel)
4. Libraries in `/home/pi/centaur` are also incompatible

**Debugging Steps**:

1. **Check if binary is accessible in container**:
```bash
sudo docker run --rm --privileged \
  -v /home/pi/centaur:/centaur:ro \
  -w /centaur \
  dgtcentaurmods/centaur-bullseye:latest \
  ls -la /centaur/centaur
```

2. **Check library dependencies in container**:
```bash
sudo docker run --rm --privileged \
  -v /home/pi/centaur:/centaur:ro \
  -w /centaur \
  dgtcentaurmods/centaur-bullseye:latest \
  ldd /centaur/centaur
```

3. **Run diagnostic script to check what's missing**:
```bash
cd ~/DGTCentaurMods/build
sudo docker run --rm --privileged \
  -v /home/pi/centaur:/centaur:ro \
  -w /centaur \
  -v $(pwd)/docker/centaur-bullseye/diagnose.sh:/diagnose.sh:ro \
  dgtcentaurmods/centaur-bullseye:latest \
  bash /diagnose.sh
```

**Note**: If commands don't produce output, try these simpler tests:

```bash
# Test 1: Basic container execution
sudo docker run --rm dgtcentaurmods/centaur-bullseye:latest echo "Container works"

# Test 2: Check if volume mount works
sudo docker run --rm \
  -v /home/pi/centaur:/centaur:ro \
  dgtcentaurmods/centaur-bullseye:latest \
  /bin/bash -c "ls -la /centaur/ | head -10"

# Test 3: Check binary exists
sudo docker run --rm \
  -v /home/pi/centaur:/centaur:ro \
  dgtcentaurmods/centaur-bullseye:latest \
  /bin/bash -c "test -f /centaur/centaur && echo 'Binary exists' || echo 'Binary NOT found'"

# Test 4: Check library dependencies (requires rebuilding image with binutils)
sudo docker run --rm \
  -v /home/pi/centaur:/centaur:ro \
  dgtcentaurmods/centaur-bullseye:latest \
  /bin/bash -c "apt-get update -qq && apt-get install -y -qq binutils > /dev/null 2>&1 && ldd /centaur/centaur"
```

4. **Run with strace to see system calls**:
```bash
sudo docker run --rm --privileged \
  --device=/dev/serial0 \
  --device=/dev/gpiomem \
  --device=/dev/spidev0.0 \
  --device=/dev/spidev0.1 \
  -v /home/pi/centaur:/centaur:ro \
  -v /sys/class/gpio:/sys/class/gpio:ro \
  -w /centaur \
  dgtcentaurmods/centaur-bullseye:latest \
  sh -c "apt-get update && apt-get install -y strace && strace /centaur/centaur 2>&1 | tail -50"
```

**Important Note**: Docker containers share the host kernel. Even though the container has Bullseye userspace libraries, it's still using Trixie's kernel. If the binary requires specific kernel interfaces that changed between Bullseye and Trixie, it may still fail. This is a fundamental limitation of Docker - it cannot change the kernel version.

## Manual Testing

### Test Docker Installation

```bash
docker --version
docker info
```

### Test Image Build

```bash
cd build/docker
./build-centaur-container.sh
docker images | grep centaur-bullseye
```

### Test Container Execution

```bash
sudo docker run --rm --privileged \
  --device=/dev/serial0 \
  --device=/dev/gpiomem \
  --device=/dev/spidev0.0 \
  --device=/dev/spidev0.1 \
  -v /home/pi/centaur:/centaur:ro \
  -v /sys/class/gpio:/sys/class/gpio:ro \
  -w /centaur \
  dgtcentaurmods/centaur-bullseye:latest \
  /bin/ls -la /centaur
```

This should list the contents of `/home/pi/centaur` from within the container.

## Limitations

- Container runs with `--privileged` for hardware access (security consideration)
- Requires Docker installation and maintenance
- Slight performance overhead compared to native execution
- Container must be rebuilt if Bullseye base image updates are needed

## Alternative Solutions

If Docker is not desired:

1. **Use Debian Bullseye**: Install Bullseye instead of Trixie on the Pi
2. **Chroot Environment**: Create a Bullseye chroot (more complex setup)
3. **Wait for Trixie-Compatible Binary**: Contact DGT for an updated binary

## Support

For issues related to:
- Docker setup: Check Docker documentation
- DGTCentaurMods integration: Check main project documentation
- Centaur binary: Contact DGT support

