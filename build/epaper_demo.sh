#!/usr/bin/env bash

git pull

#cd ~/DGTCentaurMods/DGTCentaurMods/opt
cd ~/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods

# Activate the virtual environment
source .venv/bin/activate

python -m epaper.demo
#python -m DGTCentaurMods.epaper.demo
#python DGTCentaurMods/epaper/demo.py
