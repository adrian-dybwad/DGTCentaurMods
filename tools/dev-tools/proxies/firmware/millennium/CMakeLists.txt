# SPDX-License-Identifier: Apache-2.0
# Millennium BLE Proxy Firmware for nRF52840 USB Dongle
#
# This firmware acts as a BLE man-in-the-middle proxy between a chess app
# and a real Millennium ChessLink board. All traffic is forwarded bidirectionally
# and streamed over USB CDC for analysis on the host.

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(millennium_proxy)

target_sources(app PRIVATE
    src/main.c
    src/ble_central.c
    src/ble_peripheral.c
    src/usb_console.c
    src/protocol.c
)

