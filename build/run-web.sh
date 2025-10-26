#!/bin/bash

cd ~/DGTCentaurMods/DGTCentaurMods/opt

git pull

# Stop web service if it exists
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "DGTCentaurModsWeb.service"; then
	sudo systemctl stop DGTCentaurModsWeb 2>/dev/null || true
fi

source DGTCentaurMods/.venv/bin/activate
export PYTHONPATH="$PWD"
cd DGTCentaurMods/web
export FLASK_APP=app.py
python -m flask run --host=0.0.0.0 --port=5000

# Deactivate when done
deactivate

# Start web service if it exists
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "DGTCentaurModsWeb.service"; then
	sudo systemctl start DGTCentaurModsWeb 2>/dev/null || true
fi