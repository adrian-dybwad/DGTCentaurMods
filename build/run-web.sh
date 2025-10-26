#!/bin/bash

cd ~/DGTCentaurMods/DGTCentaurMods/opt

git pull

sudo systemctl stop DGTCentaurModsWeb

source DGTCentaurMods/.venv/bin/activate
export PYTHONPATH="$PWD"
cd DGTCentaurMods/web
export FLASK_APP=app.py
python -m flask run --host=0.0.0.0 --port=5000

# Deactivate when done
deactivate

sudo systemctl start DGTCentaurModsWeb