#!/usr/bin/env bash

git pull

cd ~/DGTCentaurMods/DGTCentaurMods/opt

# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

python DGTCentaurMods/demo_epaper.py

