#!/usr/bin/env python3
"""
Text input functionality for DGT Centaur board using board pieces as a virtual keyboard.
This module provides a getText function that takes a title parameter.
"""

import time
import logging
from typing import Optional
from PIL import Image, ImageDraw, ImageFont


def getText(title):
    """
    Enter text using the board as a virtual keyboard.
    Pauses events; robust against short/partial serial reads.
    BACK deletes, TICK confirms, UP/DOWN switch pages.
    """
    from DGTCentaurMods.display import epaper
    from DGTCentaurMods.board.board import (
        pauseEvents, unPauseEvents, getBoardState, clearSerial, 
        sendPacket, _ser_read, addr1, addr2, beep, SOUND_GENERAL, 
        SOUND_WRONG, BTNBACK, BTNTICK, BTNUP, BTNDOWN, clearScreen
    )
    
    global screenbuffer
    try:
        try:
            pauseEvents()
        except Exception:
            pass

        clearstate = [0] * 64
        printableascii = (
            " !\"#$%&'()*+,-./0123456789:;<=>?@"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
            "abcdefghijklmnopqrstuvwxyz{|}~"
            + (" " * (64 * 2 - 95))
        )
        charpage = 1
        typed = ""
        changed = True

        res = getBoardState()
        if not isinstance(res, list) or len(res) != 64:
            res = [0] * 64
        if res != clearstate:
            writeTextToBuffer(0, "Remove board")
            writeText(1, "pieces")
            deadline = time.time() + 20
            while time.time() < deadline:
                time.sleep(0.4)
                res = getBoardState()
                if isinstance(res, list) and len(res) == 64 and res == clearstate:
                    break

        clearSerial()

        def _render():
            nonlocal typed, charpage
            global screenbuffer
            image = Image.new('1', (128, 296), 255)
            draw = ImageDraw.Draw(image)
            draw.text((0, 20), title, font=font18, fill=0)
            draw.rectangle([(0, 39), (128, 61)], outline=0, fill=255)
            tt = typed[-11:] if len(typed) > 11 else typed
            draw.text((0, 40), tt, font=font18, fill=0)
            page_start = (charpage - 1) * 64
            lchars = [printableascii[i] for i in range(page_start, page_start + 64)]
            for row in range(8):
                for col in range(8):
                    ch = lchars[row * 8 + col]
                    draw.text((col * 16, 80 + row * 20), ch, font=font18, fill=0)
            screenbuffer = image.copy()
            img = image.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT)
            epaper.DisplayPartial(epaper.getbuffer(img))

        def _read_fields_and_type():
            nonlocal typed, charpage
            try:
                sendPacket(b'\x83', b'')
                resp = _ser_read(10000)
                if len(resp) >= 2 and resp[0] == 133 and resp[1] == 0:
                    i = 0
                    while i < len(resp) - 1:
                        tag = resp[i]
                        if tag == 65:  # placed
                            fieldHex = resp[i + 1]
                            if 0 <= fieldHex < 64:
                                base = (charpage - 1) * 64
                                ch = printableascii[base + fieldHex]
                                typed += ch
                                beep(SOUND_GENERAL)
                                return True
                            i += 2
                        elif tag == 64:  # lifted
                            i += 2
                        else:
                            i += 1
            except Exception:
                pass
            return False

        def _read_buttons():
            try:
                sendPacket(b'\x94', b'')
                resp = _ser_read(10000)
                if len(resp) < 6:
                    return 0
                hx = resp.hex()[:-2]
                a1 = "{:02x}".format(addr1)
                a2 = "{:02x}".format(addr2)
                if hx == ("b10011" + a1 + a2 + "00140a0501000000007d47"):
                    return BTNBACK
                if hx == ("b10011" + a1 + a2 + "00140a0510000000007d17"):
                    return BTNTICK
                if hx == ("b10011" + a1 + a2 + "00140a0508000000007d3c"):
                    return BTNUP
                if hx == ("b10010" + a1 + a2 + "00140a05020000000061"):
                    return BTNDOWN
            except Exception:
                pass
            return 0

        _render()
        last_draw = 0.0
        while True:
            typed_changed = _read_fields_and_type()
            btn = _read_buttons()

            if btn == BTNBACK:
                if typed:
                    typed = typed[:-1]
                    beep(SOUND_GENERAL)
                    changed = True
                else:
                    beep(SOUND_WRONG)
            elif btn == BTNTICK:
                beep(SOUND_GENERAL)
                clearScreen()
                time.sleep(0.2)
                return typed
            elif btn == BTNUP and charpage != 1:
                charpage = 1
                beep(SOUND_GENERAL)
                changed = True
            elif btn == BTNDOWN and charpage != 2:
                charpage = 2
                beep(SOUND_GENERAL)
                changed = True

            if changed or typed_changed or (time.time() - last_draw) > 0.2:
                _render()
                last_draw = time.time()
                changed = False

            time.sleep(0.05)

    finally:
        try:
            unPauseEvents()
        except Exception:
            pass