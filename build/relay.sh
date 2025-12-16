#!/usr/bin/env bash

git pull

python ../tools/dev-tools/ble_relay_probe.py --auto-connect-millennium

