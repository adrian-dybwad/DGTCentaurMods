#!/usr/bin/env bash

git pull

cd ~/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods

# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

python epaper_demo.py

