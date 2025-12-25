# Build and Development Information

## Pi Setup

```bash
sudo raspi-config
```
1. Expand the drive to the max size
2. (Optional) Enable overlay for read-only filesystem to prevent corruption on power loss

Then reboot.

## First Setup

```bash
sudo apt update
sudo apt upgrade

# Install git & pip
sudo apt install git python3-pip

# Clone the repo
cd ~
git clone https://github.com/adrian-dybwad/Universal-Chess.git
cd Universal-Chess
python3 -m venv --system-site-packages .venv && source .venv/bin/activate && pip install -r src/universalchess/setup/requirements.txt
```

## Running

```bash
cd ~/Universal-Chess/scripts
./run.sh
```

## Bluetooth Reset

```bash
# Basic reset
sudo systemctl restart bluetooth

# Full stack reset
sudo systemctl stop bluetooth
sudo hciconfig hci0 down
sudo hciconfig hci0 up
sudo systemctl start bluetooth
```

## Development Loop

Edit code -> rebuild .deb -> reinstall -> restart services.

```bash
# Purge old package
sudo apt purge --auto-remove universal-chess

# Rebuild
cd ~/Universal-Chess/scripts
./build.sh

# Install rebuilt package
sudo apt -y install ./releases/universal-chess_*_all.deb

# Restart services
sudo systemctl restart universal-chess universal-chess-web
```

## Debugging

```bash
sudo journalctl -u universal-chess* -f
```

## Hostname

```bash
sudo hostnamectl set-hostname "dgt"
```

## SSH Key Cleanup

```bash
ssh-keygen -R dgt.local
```

## Service Management

```bash
# List services
systemctl list-units | grep universal

# Stop services
sudo systemctl stop universal-chess universal-chess-web universal-chess-stop-controller

# Start services
sudo systemctl start universal-chess universal-chess-web

# Enable at boot
sudo systemctl enable universal-chess universal-chess-web universal-chess-stop-controller
```
