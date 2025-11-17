#!/usr/bin/env bash

git pull

cd ~/DGTCentaurMods/DGTCentaurMods/opt

# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

#python DGTCentaurMods/epaper_demo.py
python -m DGTCentaurMods.epaper_demo

