#!/bin/bash
echo "=== Bluetooth Status Check ==="
echo "Service Status:"
sudo systemctl status bluetooth --no-pager -l
echo ""
echo "Adapter Status:"
sudo hciconfig
echo ""
echo "RFKill Status:"
rfkill list bluetooth
echo ""
echo "BlueZ Controller:"
bluetoothctl show 2>/dev/null || echo "No controller available"