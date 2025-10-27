Pi config util

Set read only file system to avoid corruption with power off during boot.

```
sudo raspi-config
```
Expand the drive to the max size
Enable serial0

OPTIONAL:
Goto Performance Options -> Enable overlay
sudo raspi-config nonint enable_overlayfs or sudo raspi-config nonint disable_overlayfs

Then reboot.


First setup:

```
sudo apt update
sudo apt upgrade
```

Install git & pip

```
sudo apt install git
sudo apt-get install python3-pip
```

get the repo on the pi:

```
cd ~
git clone https://github.com/adrian-dybwad/DGTCentaurMods.git
cd DGTCentaurMods/DGTCentaurModes/opt
python3 -m venv --system-site-packages DGTCentaurMods/.venv && source DGTCentaurMods/.venv/bin/activate && pip install -r DGTCentaurMods/setup/requirements.txt
```



Day-to-day development loop

Edit code → rebuild .deb (fast) → reinstall → reboot services.

```
sudo apt purge --auto-remove dgtcentaurmods

sudo systemctl disable DGTCentaurModsWeb.service
sudo systemctl disable DGTCentaurMods.service

sudo systemctl enable DGTCentaurModsWeb.service
sudo systemctl enable DGTCentaurMods.service


sudo apt -y purge dgtcentaurmods
cd ~
cd DGTCentaurMods
git pull
cd ~/DGTCentaurMods/build
./build.sh AsyncController          # or a branch/tag you’re working on
sudo cp ./releases/dgtcentaurmods_1.3.3_armhf.deb /tmp/
sudo apt -y install /tmp/dgtcentaurmods_1.3.3_armhf.deb
cp ~/DGTCentaurMods/tools/card-setup-tool/lib/font/Font.ttc /opt/DGTCentaurMods/resources/
sudo systemctl restart dgt*      # restart services (service names vary by build)
```

Run it

```
sudo chmod +x run.sh
cd /opt
./run.sh
```

```
cd /opt
python DGTCentaurMods/menu.py
```

Remove package and config files

```
sudo apt purge --auto-remove dgtcentaurmods

```

Find a package

```
apt search <name>
```

Purge your package if it’s half-installed:

```
sudo apt purge dgtcentaurmods
sudo apt autoremove --purge
```

Rebuild the .deb with fixed control and postinst.

Install the rebuilt .deb:

```
sudo apt install ./releases/dgtcentaurmods_1.3.3_armhf.deb
```

Debugging

```
sudo journalctl -u dgt* -f
```

Use `systemctl list-units | grep dgt` to discover exact service names your build installed.

Remove old ssh key
`ssh-keygen -R dgt.local`


```
sudo cp /home/pi/DGTCentaurMods/build/releases/dgtcentaurmods_1.3.3_armhf.deb /boot/firmware/DGTCentaurMods_armhf.deb
cd ~
cd DGTCentaurMods
git pull
cd ~
sudo python DGTCentaurMods/tools/card-setup-tool/firstboot.py

```