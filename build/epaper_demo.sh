#!/usr/bin/env bash

git pull

cd ~/DGTCentaurMods/DGTCentaurMods/opt

# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

python -m DGTCentaurMods.epaper.demo
#python DGTCentaurMods/epaper/demo.py
