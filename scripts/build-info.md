# Build and Development Information

## Pi Setup - if you are going to build the app on the pi from source, you *may* need to do this.

```bash
sudo raspi-config
```
1. Expand the drive to the max size
2. (Optional) In the future, could we enable overlay for read-only filesystem to prevent corruption on power loss?

Then reboot.

## First Setup on a New Pi

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

## First Install (will get the Pi hardware ready to run the app).

Before you can run the app from the ./run.sh script, you need to install it at least once.

To do this:

```bash
cd Universal-Chess/scripts
./rebuild.sh
```

After that, you should have a working copy of the app running on the Pi. In order to test changes to code, a handy helper (run.sh) will stop current service and run the code from the repo folder directly. This will still use the same resources (db etc) that the real services use.

There is also a version that will do a similar thing for the web services (api) backend. Running run-web.sh will stop the web service and run from source directly.

If you intend on working on the react application, there is a helper to run that. run-react.sh that allows you to set the api to use. For instance, if the actual board is called "dgt" (the pi's hostname) running run-react.sh will run the react app on your dev machine and use the real pi as the api server at http://dgt.local. You can set the host using run-react.sh --api http://your-pi-s-name.local if it is not dgt.

## Running from source

```bash
cd Universal-Chess/scripts
./rebuild.sh
```

```bash
cd Universal-Chess/scripts
./run.sh
```

```bash
cd Universal-Chess/scripts
./run-web.sh
```

```bash
cd Universal-Chess/scripts
./run-react.sh
```


## Bluetooth Reset

In the event something strange happens with Bluetooth, this can reset it.

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

Edit code -> run.sh -> test

## Useful Commands

```bash
# Purge old package
sudo apt purge --auto-remove universal-chess

# Rebuild
cd Universal-Chess/scripts
./build.sh

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

# Disable at boot
sudo systemctl disable universal-chess universal-chess-web universal-chess-stop-controller
```
