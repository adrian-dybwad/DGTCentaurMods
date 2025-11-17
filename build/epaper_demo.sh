#!/usr/bin/env bash

git pull

cd ~/DGTCentaurMods/DGTCentaurMods/opt

# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

# Try inverted BUSY pin logic (HIGH=busy, LOW=idle)
#export EPAPER_BUSY_INVERTED=true

python DGTCentaurMods/epaper_demo.py

