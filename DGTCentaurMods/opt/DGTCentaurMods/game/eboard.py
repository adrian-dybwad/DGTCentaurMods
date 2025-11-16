# Emulate the DGT e-board protocol
#
# Ed Nekebno
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.
#
#
# Pair first
# Connect when the display tells you to! Do not connect before.
# BACK button exits
# PLAY button resends last known check in case an app drops/ignores it
# DOWN button scrolls back boardhistory in epaper in case of sync error
# BEEPS 4 times on board start state detected (for new game)
# Castle - Pick up, put down King, pick up rook, put down rook
# Promotion - Pick up pawn, place down piece, choose piece from menu on epaper display (note you must do this
#    for both sides, even your opponent) by pressing corresponding button
#
# TODO
#
# NICE TO DO
# Detect if physical board and board array are out of sync
# Enhance illegal move takeback code (at the moment illegal moves are indicated, user can replace the pieces, putting
#     the moved piece down last. But this relies on no other pieces having been nudged, etc
# IDEAS
# Regular usb serial (in addition to bluetooth) ?

# UPDATE (REGULAR) MODE - I've not yet found anything that uses the
# non implemented items. They set the board to scan black squares,
# white squares, and back to all. For checkers I guess.
#DGT_SEND_RESET           0x40 [IMPLEMENTED]
#DGT_TO_BUSMODE           0x4a [IMPLEMENTED]
#DGT_STARTBOOTLOADER      0x4e [IMPLEMENTED]
#DGT_SEND_CLK             0x41 [FAKED - NO CLOCK]
#DGT_SEND_BRD             0x42 [IMPLEMENTED]
#DGT_SEND_UPDATE          0x43 [IMPLEMENTED]
#DGT_SEND_UPDATE_BRD      0x44 [IMPLEMENTED]
#DGT_RETURN_SERIALNR      0x45 [IMPLEMENTED]
#DGT_RETURN_BUSADRES      0x46 [IMPLEMENTED]
#DGT_SEND_TRADEMARK       0x47 [IMPLEMENTED]
#DGT_SEND_EE_MOVES        0x49 [IMPLEMENTED]
#DGT_SEND_UPDATE_NICE     0x4b [IMPLEMENTED]
#DGT_SEND_BATTERY_STATUS  0x4c [IMPLEMENTED]
#DGT_SEND_VERSION         0x4d [IMPLEMENTED]
#DGT_SEND_BRD_50B         0x50
#DGT_SCAN_50B             0x51
#DGT_SEND_BRD_50W         0x52
#DGT_SCAN_50W             0x53
#DGT_SCAN_100             0x54
#DGT_RETURN_LONG_SERIALNR 0x55 [IMPLEMENTED]
#DGT_SET_LEDS             0x60 [IMPLEMENTED]
#DGT_CLOCK_MESSAGE        0x2b [FAKED - NO CLOCK]
#DGT_BUS_UNKNOWN_2 (PING RANDOM REPLY) [NOT IMPLEMENTED - IGNORED]
# BUS
# It seems that only LiveChess uses bus mode and doesn't use them all
# therefore it doesn't seem necessary to implement them all
#DGT_BUS_SEND_CLK             (0x01 | MESSAGE_BIT) [FAKED - NO CLK]
#DGT_BUS_SEND_BRD             (0x02 | MESSAGE_BIT)
#DGT_BUS_SEND_CHANGES         (0x03 | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_REPEAT_CHANGES       (0x04 | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_SET_START_GAME       (0x05 | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_SEND_FROM_START      (0x06 | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_PING                 (0x07 | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_END_BUSMODE          (0x08 | MESSAGE_BIT)
#DGT_BUS_RESET                (0x09 | MESSAGE_BIT)
#DGT_BUS_IGNORE_NEXT_BUS_PING (0x0a | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_SEND_VERSION         (0x0b | MESSAGE_BIT) [IMPLEMENTED]
#DGT_BUS_SEND_BRD_50B         (0x0c | MESSAGE_BIT)
#DGT_BUS_SEND_ALL_D           (0x0d | MESSAGE_BIT)

import serial
import time
import sys
from os.path import exists
from DGTCentaurMods.board import *
from DGTCentaurMods.display.epaper_service import service, widgets
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, MetaData, func
import threading
import chess
import os
from PIL import Image, ImageDraw, ImageFont
from DGTCentaurMods.display import epd2in9d
import pathlib
from DGTCentaurMods.config import paths
import select
import bluetooth
import subprocess
import psutil
import atexit
from DGTCentaurMods.board.logging import log

source = ""
gamedbid = -1
session = None

debugcmds = 1

# https://github.com/well69/picochess-1/blob/master/test/dgtbrd-ruud.h
DGT_SEND_RESET = 0x40 # Puts the board into IDLE mode, cancelling any UPDATE mode
DGT_STARTBOOTLOADER = 0x4e # Hard reboot, treat like a reset
DGT_TO_BUSMODE = 0x4a
DGT_STARTBOOTLOADER = 0x4e
DGT_TRADEMARK = 0x12
DGT_RETURN_SERIALNR = 0x45
DGT_SERIALNR = 0x11
DGT_RETURN_LONG_SERIALNR = 0x55
DGT_LONG_SERIALNR = 0x22
DGT_SEND_CLK = 0x41
DGT_BWTIME = 0x0d

MESSAGE_BIT = 0x80

DGT_BUSADRES = 0x10
DGT_TO_BUSMODE = 0x4a
DGT_SEND_VERSION = 0x4d
DGT_VERSION = 0x13
DGT_SEND_BRD = 0x42
DGT_BOARD_DUMP = 0x06
DGT_SEND_UPDATE = 0x43
DGT_SEND_UPDATE_BRD = 0x44
DGT_FIELD_UPDATE = 0x0e
DGT_SEND_UPDATE_NICE = 0x4b
DGT_SET_LEDS = 0x60
DGT_CLOCK_MESSAGE = 0x2b
DGT_SEND_EE_MOVES = 0x49
DGT_EE_MOVES = 0x0f

DGT_SEND_BATTERY_STATUS = 0x4c
DGT_BATTERY_STATUS = 0x20

DGT_BUS_PING = 0x87
DGT_MSG_BUS_PING = 0x07
DGT_BUS_IGNORE_NEXT_BUS_PING = 0x8a
ignore_next_bus_ping = 0
DGT_BUS_SEND_VERSION = 0x8b
DGT_MSG_BUS_VERSION = 0x09
DGT_BUS_SEND_FROM_START = 0x86
DGT_MSG_BUS_FROM_START = 0x06
DGT_BUS_SEND_CHANGES = 0x83
DGT_MSG_BUS_UPDATE = 0x05
DGT_BUS_SEND_CLK = 0x81
DGT_BUS_SET_START_GAME = 0x85
DGT_MSG_BUS_START_GAME_WRITTEN = 0x08
DGT_BUS_REPEAT_CHANGES = 0x84
lastchangepacket = bytearray()

DGT_RETURN_BUSADRES = 0x46
DGT_SEND_TRADEMARK = 0x47

DGT_UNKNOWN_1 = 0xDF
DGT_UNKNOWN_2 = 0x92 # LiveChess code suggests this is "randomize ping" DGT_BUS_RANDOMIZE_PIN

EE_POWERUP = 0x6a
EE_EOF = 0x6b
EE_FOURROWS = 0x6c
EE_EMPTYBOARD = 0x6d
EE_DOWNLOADED = 0x6e
EE_BEGINPOS = 0x6f
EE_BEGINPOS_ROT = 0x7a
EE_START_TAG = 0x7b
EE_WATCHDOG_ACTION = 0x7c
EE_FUTURE_1 = 0x7d
EE_FUTURE_2 = 0x7e
EE_NOP = 0x7f
EE_NOP2 = 0x00
EEPROM = []

EMPTY = 0x00
WPAWN = 0x01
WROOK = 0x02
WKNIGHT = 0x03
WBISHOP = 0x04
WKING = 0x05
WQUEEN = 0x06
BPAWN = 0x07
BROOK = 0x08
BKNIGHT = 0x09
BBISHOP = 0x0a
BKING = 0x0b
BQUEEN = 0x0c
PIECE1 = 0x0d  # Magic piece: Draw
PIECE2 = 0x0e  # Magic piece: White win
PIECE3 = 0x0f  # Magic piece: Black win
cboard = bytearray([EMPTY] * 64)
boardhistory = []
turnhistory = []
MAX_BOARDHISTORY_SIZE = 100  # Maximum number of board states to prevent memory leak
litsquares = []
startstate = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')

# Initialise epaper display
service.init()

if bytearray(board.getBoardState()) != startstate:
	widgets.write_text(0,'Place pieces')
	widgets.write_text(1,'in startpos')
	# As the centaur can light up squares - let's use the
	# squares to help people out
	while bytearray(board.getBoardState()) != startstate:
		rstate = board.getBoardState()
		data = bytearray(b'\x05\x12\x00\x05')
		for x in range(0, 64):
			if x < 16 or x > 47:
				if rstate[x] != 1:
					data.append(x)
			if x > 15 and x < 48:
				if rstate[x] == 1:
					data.append(x)
		board.sendCustomLedArray(data)
		time.sleep(0.5)
	board.ledsOff()

# As we can only detect piece presence on the centaur and not pieces, we must have a known start state
log.info("Setup board")
while bytearray(board.getBoardState()) != startstate:
	time.sleep(0.5)
cboard[7] = WROOK
cboard[6] = WKNIGHT
cboard[5] = WBISHOP
cboard[4] = WQUEEN
cboard[3] = WKING
cboard[2] = WBISHOP
cboard[1] = WKNIGHT
cboard[0] = WROOK
cboard[15] = WPAWN
cboard[14] = WPAWN
cboard[13] = WPAWN
cboard[12] = WPAWN
cboard[11] = WPAWN
cboard[10] = WPAWN
cboard[9] = WPAWN
cboard[8] = WPAWN
cboard[55] = BPAWN
cboard[54] = BPAWN
cboard[53] = BPAWN
cboard[52] = BPAWN
cboard[51] = BPAWN
cboard[50] = BPAWN
cboard[49] = BPAWN
cboard[48] = BPAWN
cboard[63] = BROOK
cboard[62] = BKNIGHT
cboard[61] = BBISHOP
cboard[60] = BQUEEN
cboard[59] = BKING
cboard[58] = BBISHOP
cboard[57] = BKNIGHT
cboard[56] = BROOK
log.info("board is setup")
cb = chess.Board()
buffer1=bytearray([EMPTY] * 64)
buffer1[:] = cboard
boardhistory.append(buffer1)
turnhistory.append(1)
# Limit boardhistory size to prevent memory leak
if len(boardhistory) > MAX_BOARDHISTORY_SIZE:
	boardhistory.pop(0)
	turnhistory.pop(0)
board.ledsOff()

# Here we are emulating power on so push into the pretend eeprom
EEPROM.append(EE_NOP)
EEPROM.append(EE_NOP)
EEPROM.append(EE_NOP)
EEPROM.append(EE_POWERUP)
EEPROM.append(WROOK + 64)
EEPROM.append(7)
EEPROM.append(WKNIGHT + 64)
EEPROM.append(6)
EEPROM.append(WBISHOP + 64)
EEPROM.append(5)
EEPROM.append(WQUEEN + 64)
EEPROM.append(4)
EEPROM.append(WKING + 64)
EEPROM.append(3)
EEPROM.append(WBISHOP + 64)
EEPROM.append(2)
EEPROM.append(WKNIGHT + 64)
EEPROM.append(1)
EEPROM.append(WROOK + 64)
EEPROM.append(0)
EEPROM.append(WPAWN + 64)
EEPROM.append(15)
EEPROM.append(WPAWN + 64)
EEPROM.append(14)
EEPROM.append(WPAWN + 64)
EEPROM.append(13)
EEPROM.append(WPAWN + 64)
EEPROM.append(12)
EEPROM.append(WPAWN + 64)
EEPROM.append(11)
EEPROM.append(WPAWN + 64)
EEPROM.append(10)
EEPROM.append(WPAWN + 64)
EEPROM.append(9)
EEPROM.append(WPAWN + 64)
EEPROM.append(8)
EEPROM.append(BPAWN + 64)
EEPROM.append(55)
EEPROM.append(BPAWN + 64)
EEPROM.append(54)
EEPROM.append(BPAWN + 64)
EEPROM.append(53)
EEPROM.append(BPAWN + 64)
EEPROM.append(52)
EEPROM.append(BPAWN + 64)
EEPROM.append(51)
EEPROM.append(BPAWN + 64)
EEPROM.append(50)
EEPROM.append(BPAWN + 64)
EEPROM.append(49)
EEPROM.append(BPAWN + 64)
EEPROM.append(48)
EEPROM.append(BROOK + 64)
EEPROM.append(63)
EEPROM.append(BKNIGHT + 64)
EEPROM.append(62)
EEPROM.append(BBISHOP + 64)
EEPROM.append(61)
EEPROM.append(BQUEEN + 64)
EEPROM.append(60)
EEPROM.append(BKING + 64)
EEPROM.append(59)
EEPROM.append(BBISHOP + 64)
EEPROM.append(58)
EEPROM.append(BKNIGHT + 64)
EEPROM.append(57)
EEPROM.append(BROOK + 64)
EEPROM.append(56)
EEPROM.append(EE_BEGINPOS)
eepromlastsendpoint = 4

dodie = 0

def drawCurrentBoard():
	global cboard
	pieces = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
	for q in range(0,64):
		squarerow = (q // 8)
		squarecol = (q % 8)
		squarerow = squarerow
		squarecol = 7 - squarecol
		field = (squarerow * 8) + squarecol
		pieces[field] = cboard[q]
	for x in range(0,64):
		if pieces[x] == WPAWN:
			pieces[x]='P'
		if pieces[x] == BPAWN:
			pieces[x]='p'
		if pieces[x] == WROOK:
			pieces[x]='R'
		if pieces[x] == BROOK:
			pieces[x]='r'
		if pieces[x] == WBISHOP:
			pieces[x]='B'
		if pieces[x] == BBISHOP:
			pieces[x]='b'
		if pieces[x] == WKNIGHT:
			pieces[x]='N'
		if pieces[x] == BKNIGHT:
			pieces[x]='n'
		if pieces[x] == WQUEEN:
			pieces[x]='Q'
		if pieces[x] == BQUEEN:
			pieces[x]='q'
		if pieces[x] == WKING:
			pieces[x]='K'
		if pieces[x] == BKING:
			pieces[x]='k'
		if pieces[x] == EMPTY:
			pieces[x]=' '
	widgets.draw_board(pieces,3)

boardtoscreen = 0

paths.write_fen_log("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")

def screenUpdate():
	# Separate thread to display the screen/pieces should improve
	# responsiveness. Be nice on the epaper and only update the display
	# if the board state changes
	global cboard
	global boardtoscreen
	lastboard = ""
	while True:
		time.sleep(1.0)
		if boardtoscreen == 1 and str(cboard) != lastboard:
			lastboard = str(cboard)
			drawCurrentBoard()
		if boardtoscreen == 2:
			drawCurrentBoard()
			boardtoscreen = 1

clockfirst = 1
lclock = 0
rclock = 0
clockturn = 1 # 1 for left, 2 for right
clockpaused = 1 # If the clock is paused
showclock = 0

def clockToggle():
	# This simulates somebody pressing the buttons on the clock to start it running for the other player
	global clockfirst
	global clockturn
	global clockpaused
	log.info("clock toggled")
	if clockfirst == 1:
		log.info("first")
		clockturn = 2
		clockpaused = 0
		clockfirst = 0
	else:
		log.info("not first")
		log.info(clockturn)
		if clockturn == 1:
			clockturn = 2
			clockpaused = 0
		else:
			clockturn = 1
			clockpaused = 0
		log.info(clockturn)

# Piece and button event state variables
_piece_state = {
	'lastlift': 0,
	'kinglift': 0,
	'lastfield': -1,
	'startstateflag': 1,
	'castlemode': 0,
	'liftedthisturn': 0,
	'lastcurturn': 1,
	'promotion_waiting': False,
	'promotion_piece': None
}

def pieceEventCallback(piece_event, field, time_in_seconds):
	"""
	Callback for piece events (lift/place).
	
	Args:
		piece_event: 0 for LIFT, 1 for PLACE
		field: Chess square index (0=a1, 63=h8)
		time_in_seconds: Time from packet
	"""


	dgt_field = board.dgt_to_chess(field)

	global bt, sendupdates, WROOK,WBISHOP,WKNIGHT,WQUEEN,WKING,WPAWN,BROOK,BBISHOP,BKNIGHT,BQUEEN,BKING,BPAWN,EMPTY
	global cboard, boardhistory, turnhistory, curturn, boardtoscreen, EEPROM, dodie, cb
	global lastchangepacket, startstate, source, gamedbid, session, clockpaused, _piece_state
	
	lastlift = _piece_state['lastlift']
	kinglift = _piece_state['kinglift']
	lastfield = _piece_state['lastfield']
	castlemode = _piece_state['castlemode']
	liftedthisturn = _piece_state['liftedthisturn']
	
	if sendupdates != 1:
		return
	
	boardtoscreen = 1
	
	try:
		if piece_event == 0:  # LIFT
			# A piece has been lifted	
			log.info(f"UP: {field} {chess.square_name(field)} -> {dgt_field}")
			if curturn == 1:
				log.info("White turn")
			else:
				log.info("Black turn")
			
			if curturn == 1:
				# white
				item = cboard[dgt_field]
				if (item == WROOK or item == WBISHOP or item == WKNIGHT or item == WQUEEN or item == WKING or item == WPAWN):
					if liftedthisturn == 0:
						lastlift = cboard[dgt_field]
						lastfield = dgt_field
					liftedthisturn = liftedthisturn + 1
			if curturn == 0:
				#black
				item = cboard[dgt_field]
				if (item == BROOK or item == BBISHOP or item == BKNIGHT or item == BQUEEN or item == BKING or item == BPAWN):
					if liftedthisturn == 0:
						lastlift = cboard[dgt_field]
						lastfield = dgt_field
					liftedthisturn = liftedthisturn + 1
			
			log.info(item)
			log.info(lastlift)
			log.info(liftedthisturn)
			
			if lastlift != EMPTY and liftedthisturn < 2:
				cboard[dgt_field] = EMPTY
				tosend = bytearray(b'')
				tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(5)
				tosend.append(dgt_field)
				tosend.append(EMPTY)
				bt.send(bytes(tosend))
				time.sleep(0.2)
				log.info("SENT UP PACKET")
				buffer1 = bytearray([EMPTY] * 64)
				buffer1[:] = cboard
				boardhistory.append(buffer1)
				turnhistory.append(curturn)
				# Limit boardhistory size to prevent memory leak
				if len(boardhistory) > MAX_BOARDHISTORY_SIZE:
					boardhistory.pop(0)
					turnhistory.pop(0)
				EEPROM.append(EMPTY + 64)
				EEPROM.append(dgt_field)
				if item == WKING or item == BKING:
					if dgt_field == 3 or dgt_field == 59:
						# This is a king lift that could be part of castling.
						kinglift = 1
				else:
					kinglift = 0
			else:
				log.info("Nudge??")
		
		elif piece_event == 1:  # PLACE
			# A piece has been placed
			log.info(f"DOWN: {dgt_field} {chess.square_name(dgt_field)}")
			
			if lastlift == EMPTY:
				return
			
			# Here we check if this was a valid move to make. If not then indicate it on the board
			board.ledsOff()
			squarerow = (lastfield // 8)
			squarecol = (lastfield % 8)
			fromsq = chr(ord("a") + (7 - squarecol)) + chr(ord("1") + squarerow)
			squarerow = (dgt_field // 8)
			squarecol = (dgt_field % 8)
			tosq = chr(ord("a") + (7 - squarecol)) + chr(ord("1") + squarerow)
			mv = fromsq + tosq
			
			if curturn == 1:
				log.info("White turn")
			else:
				log.info("Black turn")
			log.info(lastlift)
			liftedthisturn = liftedthisturn - 1
			log.info(liftedthisturn)
			
			# Promotion
			promoted = 0
			if liftedthisturn == 0:
				if lastlift == WPAWN and dgt_field > 55:
					# This is a pawn promotion. Wait for button press to choose piece
					_piece_state['promotion_waiting'] = True
					_piece_state['promotion_piece'] = None
					board.sendCustomBeep(b'\x50\x08\x00\x08\x59\x08\x00')
					boardtoscreen = 0
					time.sleep(1)
					widgets.promotion_options(9)
					boardtoscreen = 2
					# Wait for button press in keyEventCallback
					while _piece_state['promotion_waiting']:
						time.sleep(0.1)
					if _piece_state['promotion_piece'] is not None:
						lastlift = _piece_state['promotion_piece']
						promoted = 1
					else:
						lastlift = WQUEEN  # Default to queen if timeout
					widgets.write_text(9,"              ")
				
				if lastlift == BPAWN and dgt_field < 8:
					_piece_state['promotion_waiting'] = True
					_piece_state['promotion_piece'] = None
					board.sendCustomBeep(b'\x50\x08\x00\x08\x59\x08\x00')
					boardtoscreen = 0
					time.sleep(1)
					widgets.promotion_options(9)
					boardtoscreen = 2
					# Wait for button press in keyEventCallback
					while _piece_state['promotion_waiting']:
						time.sleep(0.1)
					if _piece_state['promotion_piece'] is not None:
						lastlift = _piece_state['promotion_piece']
						promoted = 1
					else:
						lastlift = BQUEEN  # Default to queen if timeout
					widgets.write_text(9,"              ")
				
				if lastlift == WPAWN and dgt_field >= 40 and dgt_field <= 47:
					if (dgt_field == lastfield + 9) or (dgt_field == lastfield + 7):
						time.sleep(0.2)
						# This is an enpassant
						tosend = bytearray(b'')
						tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
						tosend.append(0)
						tosend.append(5)
						tosend.append(dgt_field - 8)
						tosend.append(EMPTY)
						bt.send(bytes(tosend))
						time.sleep(0.2)
						buffer1 = bytearray([EMPTY] * 64)
						buffer1[:] = cboard
						boardhistory.append(buffer1)
						turnhistory.append(curturn)
						# Limit boardhistory size to prevent memory leak
						if len(boardhistory) > MAX_BOARDHISTORY_SIZE:
							boardhistory.pop(0)
							turnhistory.pop(0)
						EEPROM.append(EMPTY + 64)
						EEPROM.append(dgt_field - 8)
				
				if lastlift == BPAWN and dgt_field >=16 and dgt_field <= 23:
					if (dgt_field == lastfield - 9) or (dgt_field == lastfield - 7):
						time.sleep(0.2)
						# This is an enpassant
						tosend = bytearray(b'')
						tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
						tosend.append(0)
						tosend.append(5)
						tosend.append(dgt_field + 8)
						tosend.append(EMPTY)
						bt.send(bytes(tosend))
						time.sleep(0.2)
						buffer1 = bytearray([EMPTY] * 64)
						buffer1[:] = cboard
						boardhistory.append(buffer1)
						turnhistory.append(curturn)
						# Limit boardhistory size to prevent memory leak
						if len(boardhistory) > MAX_BOARDHISTORY_SIZE:
							boardhistory.pop(0)
							turnhistory.pop(0)
						EEPROM.append(EMPTY + 64)
						EEPROM.append(dgt_field + 8)
			
			cboard[dgt_field] = lastlift
			tosend = bytearray(b'')
			tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
			tosend.append(0)
			tosend.append(5)
			tosend.append(dgt_field)
			tosend.append(lastlift)
			bt.send(bytes(tosend))
			time.sleep(0.2)
			lastchangepacket = tosend
			log.info("SENT DOWN PACKET")
			buffer1 = bytearray([EMPTY] * 64)
			buffer1[:] = cboard
			boardhistory.append(buffer1)
			turnhistory.append(curturn)
			# Limit boardhistory size to prevent memory leak
			if len(boardhistory) > MAX_BOARDHISTORY_SIZE:
				boardhistory.pop(0)
				turnhistory.pop(0)
			EEPROM.append(lastlift + 64)
			EEPROM.append(dgt_field)
			if lastfield != dgt_field:
				board.beep(board.SOUND_GENERAL)
			
			if curturn == 1:
				# white
				if lastlift != EMPTY:
					curturn = 0
					liftedthisturn = 0
				if lastfield == dgt_field:
					curturn = 1
			else:
				#black
				if lastlift != EMPTY:
					curturn = 1
					liftedthisturn = 0
				if lastfield == dgt_field:
					curturn = 0
			
			# If kinglift is 1 and lastfield is 3 or 59 then if the king has moved to
			# 1 or 5 or 61 or 57 then the user is going to move the rook next
			if kinglift == 1:
				if lastfield == 3 or lastfield == 59:
					if dgt_field == 1 or dgt_field == 5 or dgt_field == 61 or dgt_field == 57:
						log.info("Castle attempt detected")
						if curturn == 0:
							curturn = 1
							liftedthisturn = 0
						else:
							curturn = 0
							liftedthisturn = 0
			
			log.info(mv)
			if fromsq != tosq:
				if promoted == 1:
					log.info("promotion")
					if lastlift == WQUEEN or lastlift == BQUEEN:
						mv = mv + "q"
					if lastlift == WROOK or lastlift == BROOK:
						mv = mv + "r"
					if lastlift == WBISHOP or lastlift == BBISHOP:
						mv = mv + "b"
					if lastlift == WKNIGHT or lastlift == BKNIGHT:
						mv = mv + "n"
					promoted = 0
					log.info(mv)
				
				cm = chess.Move.from_uci(mv)
				legal = 1
				if cm in cb.legal_moves:
					log.info("Move is allowed")
					clockToggle()
					cb.push(cm)
					gamemove = models.GameMove(
						gameid=gamedbid,
						move=mv,
						fen=str(cb.fen())
					)
					session.add(gamemove)
					session.commit()
					log.info(cb.fen())
				else:
					# The move is not allowed or the move is the rook move after a king move in castling
					if (lastlift == WROOK or lastlift == BROOK) and (
							fromsq == "a1" or fromsq == "a8" or fromsq == "h1" or fromsq == "h8"):
						pass
					else:
						# Action the illegal move
						log.info("Move not allowed")
						squarerow = (lastfield // 8)
						squarecol = 7 - (lastfield % 8)
						tosq = (squarerow * 8) + squarecol
						squarerow = (dgt_field // 8)
						squarecol = 7 - (dgt_field % 8)
						fromsq = (squarerow * 8) + squarecol
						board.beep(board.SOUND_WRONG_MOVE)
						board.ledFromTo(fromsq, tosq)
						# Need to maintain some sort of board history
						# Then every piece up and down from this point until
						# fromsq is refilled is a history rewind
						# but we'll also need to send the board differences as updates
						boardhistory.pop()
						turnhistory.pop()
						# Handle illegal move takeback via callback
						_handle_illegal_move_takeback(fromsq)
			
			kinglift = 0
			lastfield = dgt_field
			lastlift = EMPTY
		
		# Update state
		_piece_state['lastlift'] = lastlift
		_piece_state['kinglift'] = kinglift
		_piece_state['lastfield'] = lastfield
		_piece_state['castlemode'] = castlemode
		_piece_state['liftedthisturn'] = liftedthisturn
		# Note: curturn is updated in the callback above and is a global variable
		
	except Exception as e:
		log.error(f"Error in pieceEventCallback: {e}")
		import traceback
		traceback.print_exc()

def _handle_illegal_move_takeback(fromsq):
	"""Handle illegal move takeback by waiting for piece events to restore board state"""
	global boardhistory, turnhistory, cboard, EEPROM, bt, curturn, startstate
	global _piece_state
	
	breakout = 0
	while breakout == 0:
		time.sleep(0.1)
		# Check if piece was placed back at fromsq via next callback
		if boardhistory:
			oldboard = boardhistory.pop()
			turnhistory.pop()
			# Calculate the difference between oldboard and cboard
			for x in range(0, len(oldboard)):
				if oldboard[x] != cboard[x]:
					log.info("Found difference at")
					log.info(x)
					log.info(oldboard[x])
					tosend = bytearray(b'')
					tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(5)
					tosend.append(x)
					tosend.append(oldboard[x])
					bt.send(bytes(tosend))
					EEPROM.append(oldboard[x] + 64)
					EEPROM.append(x)
			cboard[:] = oldboard
			# Check if we've restored to the illegal move source square
			if cboard[fromsq] != EMPTY:
				log.info("Piece placed back")
				breakout = 1
		
		# If the user is resetting the board to the starting position then they
		# will definitely make an illegal move. Then it will get trapped in this loop.
		r = board.getBoardState()
		if bytearray(r) == startstate:
			breakout = 1
		
		if breakout == 0:
			time.sleep(0.05)
	
	if curturn == 0:
		curturn = 1
	else:
		curturn = 0
	board.ledsOff()
	time.sleep(0.2)

def keyEventCallback(key_pressed):
	"""
	Callback for button/key press events.
	
	Args:
		key_pressed: Key enum value (Key.BACK, Key.TICK, Key.UP, Key.DOWN, Key.PLAY, Key.HELP)
	"""
	global bt, clockpaused, dodie, _piece_state
	from DGTCentaurMods.board.sync_centaur import Key
	
	try:
		# Handle promotion selection if waiting
		if _piece_state['promotion_waiting']:
			if key_pressed == Key.BACK:
				_piece_state['promotion_piece'] = WKNIGHT if curturn == 1 else BKNIGHT
				_piece_state['promotion_waiting'] = False
			elif key_pressed == Key.TICK:
				_piece_state['promotion_piece'] = WBISHOP if curturn == 1 else BBISHOP
				_piece_state['promotion_waiting'] = False
			elif key_pressed == Key.UP:
				_piece_state['promotion_piece'] = WQUEEN if curturn == 1 else BQUEEN
				_piece_state['promotion_waiting'] = False
			elif key_pressed == Key.DOWN:
				_piece_state['promotion_piece'] = WROOK if curturn == 1 else BROOK
				_piece_state['promotion_waiting'] = False
			return
		
		# Handle regular button presses
		tosend = bytearray(b'')
		tosend.append(DGT_BWTIME | MESSAGE_BIT)
		tosend.append(0)
		tosend.append(10)
		ack0 = 0x10
		ack1 = 0x88
		ack2 = 0x0
		
		if key_pressed == Key.BACK:
			ack3 = 0x31
			board.beep(board.SOUND_GENERAL)
		elif key_pressed == Key.TICK:
			ack3 = 0x35
			board.beep(board.SOUND_GENERAL)
		elif key_pressed == Key.UP:
			ack3 = 0x34
			board.beep(board.SOUND_GENERAL)
		elif key_pressed == Key.DOWN:
			ack3 = 0x32
			board.beep(board.SOUND_GENERAL)
		elif key_pressed == Key.HELP:
			dodie = 1
			board.beep(board.SOUND_GENERAL)
			return
		elif key_pressed == Key.PLAY:
			ack3 = 0x33
			board.beep(board.SOUND_GENERAL)
			clockpaused = 0
		else:
			return
		
		tosend.append(round(((ack2 & 0x80) / 8) + ((ack3 & 0x80) / 4) + 0x0a))
		tosend.append(ack0 & 0x7f)
		tosend.append(ack1 & 0x7f)
		tosend.append(round(((ack0 & 0x80) / 8) + ((ack1 & 0x80) / 4) + 0x0a))
		tosend.append(ack2 & 0x7f)
		tosend.append(ack3 & 0x7f)
		tosend.append(0)
		log.info(tosend.hex())
		bt.send(bytes(tosend))
		
	except Exception as e:
		log.error(f"Error in keyEventCallback: {e}")
		import traceback
		traceback.print_exc()

def pieceMoveDetectionThread():
	# Separate thread to monitor board state and handle timer-based checks
	# Piece and button events are now handled via callbacks
	global bt
	global sendupdates
	global timer
	global WROOK,WBISHOP,WKNIGHT,WQUEEN,WKING,WPAWN,BROOK,BBISHOP,BKNIGHT,BQUEEN,BKING,BPAWN,EMPTY
	global cboard
	global boardhistory
	global turnhistory
	global curturn
	global boardtoscreen
	global EEPROM
	global dodie
	global cb
	global lastchangepacket
	global startstate
	global source
	global gamedbid
	global session
	global clockpaused
	global _piece_state
	
	lastlift = _piece_state['lastlift']
	kinglift = _piece_state['kinglift']
	lastfield = _piece_state['lastfield']
	startstateflag = _piece_state['startstateflag']
	castlemode = _piece_state['castlemode']
	liftedthisturn = _piece_state['liftedthisturn']
	lastcurturn = _piece_state['lastcurturn']
	while True:
		time.sleep(0.3)
		if sendupdates == 1:
			boardtoscreen = 1
		
		# Update state from global _piece_state
		lastcurturn = _piece_state['lastcurturn']
		startstateflag = _piece_state['startstateflag']
		
		# Update _piece_state with current values
		_piece_state['lastcurturn'] = lastcurturn
		_piece_state['startstateflag'] = startstateflag
		
		# Monitor turn changes and board state
		if lastcurturn != curturn:
			lastcurturn = curturn
			_piece_state['lastcurturn'] = lastcurturn
			log.info("--------------")
			paths.write_fen_log(cb.fen())
			if curturn == 1:
				log.info("White turn")
				widgets.write_text(10,"White turn")
			else:
				log.info("Black turn")
				widgets.write_text(10,"Black turn")

			timer = timer + 1
			if timer > 5:
				r = board.getBoardState()
				if bytearray(r) == startstate and startstateflag == 0:
					log.info("start state detected")
					clockpaused = 1
					paths.write_fen_log("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
					board.sendCustomBeep(b'\x50\x08\x00\x08\x50\x08\x00\x08\x59\x08\x00\x08\x50\x08\x00\x08\x00')
					boardhistory = []
					turnhistory = []
					startstateflag = 1
					cboard = bytearray([EMPTY] * 64)
					cboard[7] = WROOK
					cboard[6] = WKNIGHT
					cboard[5] = WBISHOP
					cboard[4] = WQUEEN
					cboard[3] = WKING
					cboard[2] = WBISHOP
					cboard[1] = WKNIGHT
					cboard[0] = WROOK
					cboard[15] = WPAWN
					cboard[14] = WPAWN
					cboard[13] = WPAWN
					cboard[12] = WPAWN
					cboard[11] = WPAWN
					cboard[10] = WPAWN
					cboard[9] = WPAWN
					cboard[8] = WPAWN
					cboard[55] = BPAWN
					cboard[54] = BPAWN
					cboard[53] = BPAWN
					cboard[52] = BPAWN
					cboard[51] = BPAWN
					cboard[50] = BPAWN
					cboard[49] = BPAWN
					cboard[48] = BPAWN
					cboard[63] = BROOK
					cboard[62] = BKNIGHT
					cboard[61] = BBISHOP
					cboard[60] = BQUEEN
					cboard[59] = BKING
					cboard[58] = BBISHOP
					cboard[57] = BKNIGHT
					cboard[56] = BROOK
					buffer1 = bytearray([EMPTY] * 64)
					buffer1[:] = cboard
					boardhistory.append(buffer1)
					turnhistory.append(1)
					# Limit boardhistory size to prevent memory leak
					if len(boardhistory) > MAX_BOARDHISTORY_SIZE:
						boardhistory.pop(0)
						turnhistory.pop(0)
					for x in range(0,64):
						tosend = bytearray(b'')
						tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
						tosend.append(0)
						tosend.append(5)
						tosend.append(x)
						tosend.append(cboard[x])
						bt.send(bytes(tosend))
						#bt.flush()
					EEPROM.append(WROOK + 64)
					EEPROM.append(7)
					EEPROM.append(WKNIGHT + 64)
					EEPROM.append(6)
					EEPROM.append(WBISHOP + 64)
					EEPROM.append(5)
					EEPROM.append(WQUEEN + 64)
					EEPROM.append(4)
					EEPROM.append(WKING + 64)
					EEPROM.append(3)
					EEPROM.append(WBISHOP + 64)
					EEPROM.append(2)
					EEPROM.append(WKNIGHT + 64)
					EEPROM.append(1)
					EEPROM.append(WROOK + 64)
					EEPROM.append(0)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(15)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(14)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(13)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(12)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(11)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(10)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(9)
					EEPROM.append(WPAWN + 64)
					EEPROM.append(8)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(55)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(54)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(53)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(52)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(51)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(50)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(49)
					EEPROM.append(BPAWN + 64)
					EEPROM.append(48)
					EEPROM.append(BROOK + 64)
					EEPROM.append(63)
					EEPROM.append(BKNIGHT + 64)
					EEPROM.append(62)
					EEPROM.append(BBISHOP + 64)
					EEPROM.append(61)
					EEPROM.append(BQUEEN + 64)
					EEPROM.append(60)
					EEPROM.append(BKING + 64)
					EEPROM.append(59)
					EEPROM.append(BBISHOP + 64)
					EEPROM.append(58)
					EEPROM.append(BKNIGHT + 64)
					EEPROM.append(57)
					EEPROM.append(BROOK + 64)
					EEPROM.append(56)
					EEPROM.append(EE_BEGINPOS)
					cb = chess.Board()
					board.ledsOff()
					curturn = 1
					lastcurturn = 0
					lastlift = 0
					kinglift = 0
					lastfield = -1
					startstateflag = 1
					castlemode = 0
					liftedthisturn = 0
					# Log a new game in the db
					game = models.Game(
						source=source
					)
					log.info(game)
					session.add(game)
					session.commit()
					# Get the max game id as that is this game id and fill it into gamedbid
					gamedbid = session.query(func.max(models.Game.id)).scalar()
					# Now make an entry in GameMove for this start state
					gamemove = models.GameMove(
						gameid=gamedbid,
						move='',
						fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
					)
					session.add(gamemove)
					session.commit()
					widgets.write_text(10, "White turn")
				else:
					if bytearray(r) != startstate:
						startstateflag = 0
				timer = 0

# Import shared Bluetooth controller
from DGTCentaurMods.board.bluetooth_controller import BluetoothController

drawCurrentBoard()

# Create Bluetooth controller instance and start pairing thread
bluetooth_controller = BluetoothController()
pairThread = bluetooth_controller.start_pairing_thread()

# Kill rfcomm if it is started
os.system('sudo service rfcomm stop')
time.sleep(2)
for p in psutil.process_iter(attrs=['pid', 'name']):
	if str(p.info["name"]) == "rfcomm":
		p.kill()
iskilled = 0
log.info("checking killed")
while iskilled == 0:
	iskilled = 1
	for p in psutil.process_iter(attrs=['pid', 'name']):
		if str(p.info["name"]) == "rfcomm":
			iskilled = 0
	time.sleep(0.1)

kill = 0

server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
server_sock.bind(("", bluetooth.PORT_ANY))
server_sock.settimeout(0.5)
server_sock.listen(1)
port = server_sock.getsockname()[1]
uuid = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
bluetooth.advertise_service(server_sock, "UARTClassicServer", service_id=uuid,
                            service_classes=[uuid, bluetooth.SERIAL_PORT_CLASS],
                            profiles=[bluetooth.SERIAL_PORT_PROFILE],
                            # protocols=[bluetooth.OBEX_UUID]
                            )

log.info("Waiting for connection on RFCOMM channel: " + str(port))
widgets.write_text(0,'Connect remote')
widgets.write_text(1,'Device Now')
connected = 0
while connected == 0 and kill == 0:
	try:
		bt, client_info = server_sock.accept()
		connected = 1
	except:
		# Check for BACK button via callback (handled in keyEventCallback)
		# Access controller through board module
		from DGTCentaurMods.board import board as board_module
		key_pressed = board_module.controller.get_and_reset_last_key()
		if key_pressed is not None:
			from DGTCentaurMods.board.sync_centaur import Key
			if key_pressed == Key.BACK:
				kill = 1
		time.sleep(0.1)

if kill == 1:
	# Clean up database session before exit
	if session is not None:
		try:
			session.close()
		except Exception:
			pass
	os._exit(0)

log.info("Connected")

#bt = serial.Serial("/dev/rfcomm0",baudrate=9600, timeout=10)
widgets.clear_screen()
widgets.write_text(0,'Connected')
log.info("pieceMoveDetectionThread started")

# Set up callbacks for piece and button events
board.subscribeEvents(keyEventCallback, pieceEventCallback, timeout=100000)

cb = chess.Board()
board.ledsOff()

source = "eboard.py"
Session = sessionmaker(bind=models.engine)
session = Session()

# Register cleanup function to ensure session is closed on exit
def cleanup_session():
	"""Ensure database session is closed on program exit."""
	global session
	if session is not None:
		try:
			session.close()
		except Exception:
			pass

atexit.register(cleanup_session)

# Log a new game in the db
game = models.Game(
	source=source
)
log.info(game)
session.add(game)
session.commit()
# Get the max game id as that is this game id and fill it into gamedbid
gamedbid = session.query(func.max(models.Game.id)).scalar()
# Now make an entry in GameMove for this start state
gamemove = models.GameMove(
	gameid = gamedbid,
	move = '',
	fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
)
session.add(gamemove)
session.commit()

scrUpd = threading.Thread(target=screenUpdate, args=())
scrUpd.daemon = True
scrUpd.start()

sendupdates = 0
timer = 0
# 0 for black, 1 for white
curturn = 1
widgets.write_text(10,"White turn")

pMove = threading.Thread(target=pieceMoveDetectionThread,args=())
pMove.daemon = True
pMove.start()

# Clear any remaining data sent from the board
try:
	#board.clearBoardData()
	pass
except:
	pass

lastlift = EMPTY

cb = chess.Board()
curturn = 1
lastlift = 0
lastfield = -1
lastcurturn = 0
boardhistory = []
turnhistory = []
serialcount = 0
reversed = 0

time.sleep(0.2)

def sendClockData():
	# Sends a BWTIME message.
	global bt
	global lclock
	global rclock
	global clockturn
	global clockpaused
	log.info("sending clock")
	tosend = bytearray(b'')
	tosend.append(DGT_BWTIME | MESSAGE_BIT)
	tosend.append(0)
	tosend.append(10)
	tclock = lclock
	lh = tclock // 3600
	tclock = tclock % 3600
	lm = tclock // 60
	lmp1 = lm // 10
	lmp2 = lm % 10
	lm = (lmp1 << 4) + lmp2
	tclock = tclock % 60
	ls = tclock
	lsp1 = ls // 10
	lsp2 = ls % 10
	ls = (lsp1 << 4) + lsp2
	tosend.append(lh) # l h
	tosend.append(lm) # l m
	tosend.append(ls) # l s
	tclock = rclock
	rh = tclock // 3600
	tclock = tclock % 3600
	rm = tclock // 60
	rmp1 = rm // 10
	rmp2 = rm % 10
	rm = (rmp1 << 4) + rmp2
	tclock = tclock % 60
	rs = tclock
	rsp1 = rs // 10
	rsp2 = rs % 10
	rs = (rsp1 << 4) + rsp2
	tosend.append(rh) # r h
	tosend.append(rm) # r m
	tosend.append(rs) # r s
	flags = 1
	if clockpaused == 0:
		flags = flags | 0x01
	if clockturn == 2:
		flags = flags | 0x02
	if clockturn == 1:
		flags = flags | 0x08
	if clockturn == 2:
		flags = flags | 0x10
	tosend.append(flags) # flags
	log.info("Sending clock data: " + tosend.hex())
	bt.send(bytes(tosend))
	#bt.flush()

def clockRun():
	# Decrement the clock
	global lclock
	global rclock
	global clockturn
	global clockpaused
	while True:
		if clockturn == 1:
			if lclock > 0:
				if clockpaused == 0:
					lclock = lclock - 1
				lmin = lclock // 60
				lsec = lclock % 60
				rmin = rclock // 60
				rsec = rclock % 60
				timestr = "{:02d}".format(lmin) + ":" + "{:02d}".format(lsec) + "       " + "{:02d}".format(rmin) + ":" + "{:02d}".format(rsec)
				if showclock == 1:
					widgets.write_text(12,timestr)
		if clockturn == 2:
			if rclock > 0:
				if clockpaused == 0:
					rclock = rclock - 1
				lmin = lclock // 60
				lsec = lclock % 60
				rmin = rclock // 60
				rsec = rclock % 60
				timestr = "{:02d}".format(lmin) + ":" + "{:02d}".format(lsec) + "       " + "{:02d}".format(
					rmin) + ":" + "{:02d}".format(rsec)
				if showclock == 1:
					widgets.write_text(12, timestr)
		sendClockData()
		time.sleep(1)

clkThread = threading.Thread(target=clockRun, args=())
clkThread.daemon = True
clkThread.start()

while True and dodie == 0:
	try:
		data=bt.recv(1)
		if len(data) > 0:
			handled = 0
			if data[0] == DGT_SEND_RESET or data[0] == DGT_STARTBOOTLOADER:
				# Puts the board in IDLE mode
				#board.clearBoardData()
				#widgets.write_text(0, 'Init')
				#widgets.write_text(1, '         ')
				if debugcmds == 1:
					log.info("DGT_SEND_RESET")
				sendupdates = 0
				handled = 1
			if data[0] == DGT_TO_BUSMODE:
				# Puts the board in BUS mode
				#log.info("Bus mode")
				if debugcmds == 1:
					log.info("DGT_TO_BUSMODE")
				handled = 1
			if data[0] == DGT_RETURN_BUSADRES:
				if debugcmds == 1:
					log.info("DGT_RETURN_BUSADRES")
				tosend = bytearray(b'\x00\x00\x05\x08\x01')
				tosend[0] = DGT_BUSADRES | MESSAGE_BIT
				#tosend.append(board.checksum(tosend))
				bt.send(bytes(tosend))
				#bt.flush()
				sentbus = 1
				handled = 1
			if data[0] == DGT_SEND_EE_MOVES:
				# Send EEPROM followed by EE_EOF
				if debugcmds == 1:
					log.info("DGT_SEND_EE_MOVES")
				tosend = bytearray(b'')
				tosend[0] = DGT_EE_MOVES | MESSAGE_BIT
				for j in range(0,len(EEPROM)-1):
					tosend.append(EEPROM[j])
				tosend.append(EE_EOF)
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_SEND_TRADEMARK:
				# Send DGT Trademark Message
				if debugcmds == 1:
					log.info("DGT_SEND_TRADEMARK")
				tosend = bytearray(b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
				tosend[0] = DGT_TRADEMARK | MESSAGE_BIT
				tosend[1] = 0
				tosend[2] = 36
				tosend[3] = ord('D')
				tosend[4] = ord('i')
				tosend[5] = ord('g')
				tosend[6] = ord('i')
				tosend[7] = ord('t')
				tosend[8] = ord('a')
				tosend[9] = ord('l')
				tosend[10] = ord(' ')
				tosend[11] = ord('G')
				tosend[12] = ord('a')
				tosend[13] = ord('m')
				tosend[14] = ord('e')
				tosend[15] = ord(' ')
				tosend[16] = ord('T')
				tosend[17] = ord('e')
				tosend[18] = ord('c')
				tosend[19] = ord('h')
				tosend[20] = ord('n')
				tosend[21] = ord('o')
				tosend[22] = ord('l')
				tosend[23] = ord('o')
				tosend[24] = ord('g')
				tosend[25] = ord('y')
				tosend[26] = ord(' ')
				tosend[27] = ord('E')
				tosend[28] = ord('m')
				tosend[29] = ord('u')
				tosend[30] = ord('l')
				tosend[31] = ord('a')
				tosend[32] = ord('t')
				tosend[33] = ord('i')
				tosend[34] = ord('o')
				tosend[35] = ord('n')
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_BUS_PING:
				# Received a ping message
				# The message actually has two more bytes and a checksum
				#log.info("bus pinged")
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_PING " + dump.hex())
				#print(dump.hex())
				if ignore_next_bus_ping == 1 and dump[0] == 0 and dump[1] == 0:
					ignore_next_bus_ping = 0
					#log.info("ignoring")
					handled = 1
				else:
					#log.info(dump.hex())
					tosend = bytearray(b'')
					tosend.append(DGT_MSG_BUS_PING | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(6)
					tosend.append(8)
					tosend.append(1)
					tosend.append(board.checksum(tosend))
					time.sleep(0.05)
					bt.send(bytes(tosend))
					#bt.flush()
					handled = 1
			if data[0] == DGT_BUS_IGNORE_NEXT_BUS_PING:
				# A ping message and response but ignore the next ping!
				# The message actually has two more bytes and a checksum
				#log.info("ignore next bus ping")
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_IGNORE_NEXT_BUS_PING " + dump.hex())
				#print(dump.hex())
				tosend = bytearray(b'')
				tosend.append(DGT_MSG_BUS_PING | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(6)
				tosend.append(8)
				tosend.append(1)
				tosend.append(board.checksum(tosend))
				time.sleep(0.05)
				bt.send(bytes(tosend))
				#bt.flush()
				ignore_next_bus_ping = 1
				handled = 1
			if data[0] == DGT_BUS_SEND_VERSION:
				# Send Version to bus
				#log.info("sending version to bus")
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_SEND_VERSION " + dump.hex())
				tosend = bytearray(b'')
				tosend.append(DGT_MSG_BUS_VERSION | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(8)
				tosend.append(8)
				tosend.append(1)
				tosend.append(1)
				tosend.append(2)
				tosend.append(board.checksum(tosend))
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_BUS_SEND_CLK:
				# Don't handle this for now but we still need to clear the extra bytes
				# with ourbus  address and checksum
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_SEND_CLK " + dump.hex())
				handled = 1
			if data[0] == DGT_BUS_SEND_FROM_START:
				#log.info("Sending EEPROM data from start")
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_SEND_FROM_START " + dump.hex())
				# find the last occurrence of EE_START in the EEPROM
				offset = -1
				for i in range(len(EEPROM) - 1, -1, -1):
					if EEPROM[i] == EE_START_TAG:
						offset = i
						break
				tosend = bytearray(b'')
				tosend.append(DGT_MSG_BUS_FROM_START | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(6)
				tosend.append(8)
				tosend.append(1)
				if offset == -1:
					#log.info("Sending but no data")
					tosend.append(board.checksum(tosend))
					#log.info(tosend.hex())
					bt.send(bytes(tosend))
					#bt.flush()
					handled = 1
				else:
					#log.info("Sending with data")
					for i in range(offset, len(EEPROM)-1):
						tosend.append(EEPROM[i])
						tosend[2] = len(tosend) + 1
						tosend.append(board.checksum(tosend))
						#log.info(tosend.hex())
						bt.send(bytes(tosend))
						#bt.flush()
						handled = 1
				sendupdates = 1
			if data[0] == DGT_BUS_SEND_CHANGES:
				#log.info("Sending changes since last request")
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_SEND_CHANGES " + dump.hex())
				tosend = bytearray(b'')
				tosend.append(DGT_MSG_BUS_UPDATE | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(6)
				tosend.append(8)
				tosend.append(1)
				for i in range(eepromlastsendpoint, len(EEPROM)):
					tosend.append(EEPROM[i])
				tosend[2] = len(tosend) + 1
				tosend.append(board.checksum(tosend))
				#print(tosend.hex())
				bt.send(bytes(tosend))
				#bt.flush()
				lastchangepacket = tosend
				eepromlastsendpoint = len(EEPROM)
				handled = 1
			if data[0] == DGT_BUS_REPEAT_CHANGES:
				log.info("repeat changes")
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_REPEAT_CHANGES " + dump.hex())
				tosend = lastchangepacket
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_UNKNOWN_2:
				# This is a bus mode packet. But I don't know what it does. It seems it can be ignored though
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_UNKNOWN_2 (PING RANDOM REPLY) " + dump.hex())
				handled = 1
			if data[0] == DGT_BUS_SET_START_GAME:
				dump = bt.recv(3)
				if debugcmds == 1:
					log.info("DGT_BUS_SET_START_GAME " + dump.hex())
				log.info("Bus set start game")
				paths.write_fen_log("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
				# Write EE_START_TAG to EEPROM
				# Followed by piece positions
				# Return DGT_MSG_BUS_START_GAME_WRITTEN message
				EEPROM.append(EE_START_TAG)
				EEPROM.append(WROOK + 64)
				EEPROM.append(7)
				EEPROM.append(WKNIGHT + 64)
				EEPROM.append(6)
				EEPROM.append(WBISHOP + 64)
				EEPROM.append(5)
				EEPROM.append(WQUEEN + 64)
				EEPROM.append(4)
				EEPROM.append(WKING + 64)
				EEPROM.append(3)
				EEPROM.append(WBISHOP + 64)
				EEPROM.append(2)
				EEPROM.append(WKNIGHT + 64)
				EEPROM.append(1)
				EEPROM.append(WROOK + 64)
				EEPROM.append(0)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(15)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(14)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(13)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(12)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(11)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(10)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(9)
				EEPROM.append(WPAWN + 64)
				EEPROM.append(8)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(55)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(54)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(53)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(52)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(51)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(50)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(49)
				EEPROM.append(BPAWN + 64)
				EEPROM.append(48)
				EEPROM.append(BROOK + 64)
				EEPROM.append(63)
				EEPROM.append(BKNIGHT + 64)
				EEPROM.append(62)
				EEPROM.append(BBISHOP + 64)
				EEPROM.append(61)
				EEPROM.append(BQUEEN + 64)
				EEPROM.append(60)
				EEPROM.append(BKING + 64)
				EEPROM.append(59)
				EEPROM.append(BBISHOP + 64)
				EEPROM.append(58)
				EEPROM.append(BKNIGHT + 64)
				EEPROM.append(57)
				EEPROM.append(BROOK + 64)
				EEPROM.append(56)
				EEPROM.append(EE_BEGINPOS)
				tosend = bytearray(b'')
				tosend.append(DGT_MSG_BUS_START_GAME_WRITTEN | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(6)
				tosend.append(8)
				tosend.append(1)
				tosend.append(board.checksum(tosend))
				time.sleep(0.05)
				bt.send(bytes(tosend))
				#bt.flush()
				cb = chess.Board()
				curturn = 1
				lastlift = 0
				lastfield = -1
				lastcurturn = 0
				boardhistory = []
				turnhistory = []
				board.ledsOff()
				sendupdates = 1
				handled = 1
			if data[0] == DGT_RETURN_SERIALNR:
				# Return our serial number
				if debugcmds == 1:
					log.info("DGT_RETURN_SERIALNR")
				tosend = bytearray(b'')
				tosend.append(DGT_SERIALNR | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(8)
				tosend.append(ord('1'))
				tosend.append(ord('2'))
				tosend.append(ord('3'))
				tosend.append(ord('4'))
				tosend.append(ord('5'))
				bt.send(bytes(tosend))
				#bt.flush()
				bt.send(bytes(tosend))
				#bt.flush()
				bt.send(bytes(tosend))
				#bt.flush()
				# If something is just repeatedly asking for the serial then start sending updates anyway
				serialcount = serialcount + 1
				if serialcount > 5:
					sendupdates = 1
					# Also send a version
					tosend = bytearray(b'')
					tosend.append(DGT_VERSION | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(5)
					tosend.append(1)
					tosend.append(2)
					bt.send(bytes(tosend))
					#bt.flush()
				handled = 1
			if data[0] == DGT_RETURN_LONG_SERIALNR:
				# Return our long serial number
				if debugcmds == 1:
					log.info("DGT_RETURN_LONG_SERIALNR")
				tosend = bytearray(b'')
				tosend.append(DGT_LONG_SERIALNR | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(13)
				tosend.append(ord('3'))
				tosend.append(ord('.'))
				tosend.append(ord('3'))
				tosend.append(ord('6'))
				tosend.append(ord('0'))
				tosend.append(ord('1'))
				tosend.append(ord('2'))
				tosend.append(ord('3'))
				tosend.append(ord('4'))
				tosend.append(ord('5'))
				bt.send(bytes(tosend))
				#bt.flush()
				bt.send(bytes(tosend))
				#bt.flush()
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_SEND_VERSION:
				# Return our serial number
				if debugcmds == 1:
					log.info("DGT_SEND_VERSION")
				tosend = bytearray(b'')
				tosend.append(DGT_VERSION | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(5)
				tosend.append(1)
				tosend.append(2)
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_SEND_BRD:
				# Send the board
				if debugcmds == 1:
					log.info("DGT_SEND_BRD")
				tosend = bytearray(b'')
				tosend.append(DGT_BOARD_DUMP | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(67)
				for x in range(0,64):
					tosend.append(cboard[x])
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if data[0] == DGT_SET_LEDS:
				# LEDs! Not sure about this code, but at the moment it works with Chess for Android
				# Note the mapping for the centaur goes 0 (a1) to 63 (h8)
				# This mapping goes 0 (h1) to 63 (a8)
				dd = bt.recv(5)
				if debugcmds == 1:
					log.info("DGT_SET_LEDS " + dd.hex())
				#print(dd.hex())
				if dd[1] == 0:
					# Off
					log.info("off")
					tos = 0
					froms = 0
					if reversed == 1:
						squarerow = 7 - (dd[2] // 8)
						squarecol = 7 - (dd[2] % 8)
						froms = (squarerow * 8) + squarecol
						squarerow = 7 - (dd[3] // 8)
						squarecol = 7 - (dd[3] % 8)
						tos = (squarerow * 8) + squarecol
					else:
						froms = dd[2]
						tos = dd[3]
					litsquares = list(filter(lambda a: a != froms, litsquares))
					litsquares = list(filter(lambda a: a != tos, litsquares))
					if (dd[2] == 0 and dd[3] >= 63) or (dd[2] == 64):
						# This seems to be some code to turn the lights off
						litsquares = []
						#board.ledsOff()
						# The 0 63 in particular seems to define reversed mode in chess for android
						if (dd[2] == 0 and dd[3] == 63):
							reversed = 1
					#print(len(litsquares))
					if len(litsquares) > 0:
						board.ledsOff()
						data = bytearray(b'\x05\x05\x00\x05')
						for x in range(0, len(litsquares)):
							data.append(litsquares[x])
						log.info(data.hex())
						board.sendCustomLedArray(data)
						time.sleep(0.2)
					else:
						board.ledsOff()
				if dd[1] == 1:
					# On
					#print("on")
					tos = 0
					froms = 0
					if reversed == 1:
						squarerow = 7 - (dd[2] // 8)
						squarecol = 7 - (dd[2] % 8)
						froms = (squarerow * 8) + squarecol
						squarerow = 7 - (dd[3] // 8)
						squarecol = 7 - (dd[3] % 8)
						tos = (squarerow * 8) + squarecol
					else:
						froms = dd[2]
						tos = dd[3]
					board.ledsOff()
					board.ledFromTo(board.dgt_to_chess(froms), board.dgt_to_chess(tos))
					time.sleep(0.2)
				handled = 1
			if data[0] == DGT_SEND_UPDATE or data[0] == DGT_SEND_UPDATE_BRD:
				# Send an update
				if debugcmds == 1:
					if data[0] == DGT_SEND_UPDATE:
						log.info("DGT_SEND_UPDATE")
					else:
						log.info("DGT_SEND_UPDATE_BRD")
				tosend = bytearray(b'')
				tosend.append(DGT_FIELD_UPDATE | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(5)
				tosend.append(0)
				tosend.append(cboard[0])
				bt.send(bytes(tosend))
				#bt.flush()
				#widgets.write_text(0, 'PLAY   ')
				#widgets.write_text(1, '         ')
				# Here let's actually loop through reading the board states
				sendupdates = 1
				handled = 1
			if data[0] == DGT_SEND_UPDATE_NICE:
				#widgets.write_text(0, 'PLAY   ')
				#widgets.write_text(1, '         ')
				if debugcmds == 1:
					log.info("DGT_SEND_UPDATE_NICE")
				sendupdates = 1
				handled = 1
			if data[0] == DGT_CLOCK_MESSAGE:
				# For now don't display the clock, maybe later. But the other device acts as it
				# Just drop the data
				if debugcmds == 1:
					log.info("DGT_CLOCK_MESSAGE")
				sz = bt.recv(1)
				sz = sz[0]
				d = bt.recv(sz)
				log.info("****** " + d.hex())
				clkhandled = 0
				if d.hex() == "030300":
					# Clears the message and shows normal clock times
					# It is responded to with clock data. For now fake it
					#sendClockData()
					tosend = bytearray(b'')
					tosend.append(DGT_BWTIME | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(10)
					ack0 = 0x10
					ack1 = 0x81
					ack2 = 0x0
					ack3 = 0
					tosend.append(round(((ack2 & 0x80)/8) + ((ack3 & 0x80)/4) + 0x0a)) # 4  0
					tosend.append(ack0 & 0x7f) # 5  1
					tosend.append(ack1 & 0x7f) # 6  2
					tosend.append(round(((ack0 & 0x80)/8) + ((ack1 & 0x80)/4) + 0x0a)) # 7  3
					tosend.append(ack2 & 0x7f) # 8  4
					tosend.append(ack3 & 0x7f) # 9  5
					tosend.append(0) # 10
					log.info(tosend.hex())
					bt.send(bytes(tosend))
					#bt.flush()
					clkhandled = 1
				if d.hex() == "030900":
					# This is requesting the clock version
					tosend = bytearray(b'')
					tosend.append(DGT_BWTIME | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(10)
					ack0 = 0x10
					ack1 = 0x09
					ack2 = 0x12
					ack3 = 0
					tosend.append(round(((ack2 & 0x80)/8) + ((ack3 & 0x80)/4) + 0x0a)) # 4  0
					tosend.append(ack0 & 0x7f) # 5  1
					tosend.append(ack1 & 0x7f) # 6  2
					tosend.append(round(((ack0 & 0x80)/8) + ((ack1 & 0x80)/4) + 0x0a)) # 7  3
					tosend.append(ack2 & 0x7f) # 8  4
					tosend.append(ack3 & 0x7f) # 9  5
					tosend.append(0) # 10
					log.info(tosend.hex())
					bt.send(bytes(tosend))
					#bt.flush()
					clkhandled = 1
				if d.hex()[0:4] == "030a":
					# This is asking to set the clock setnrun
					log.info("setting the clock")
					# clockturn clockpaused showclock
					lh = d[2]
					lm = d[3]
					ls = d[4]
					rh = d[5]
					rm = d[6]
					rs = d[7]
					ctl = d[8]
					log.info(lh)
					log.info(lm)
					log.info(ls)
					log.info(rh)
					log.info(rm)
					log.info(rs)
					lclock = (int(str(lh)) * 3600) + (int(str(lm)) * 60) + (int(str(ls)))
					rclock = (int(str(rh)) * 3600) + (int(str(rm)) * 60) + (int(str(rs)))
					log.info("Set the clocks")
					log.info(lclock)
					log.info(rclock)
					showclock = 1
					clockturn = 1
					log.info("left turn")
					if ctl & 0x02 > 0:
						clockturn = 2
						log.info("right turn")
					if ctl & 0x04 > 0:
						clockpaused = 1
						log.info("paused")
					else:
						clockpaused = 0
						log.info("running")
					tosend = bytearray(b'')
					tosend.append(DGT_BWTIME | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(10)
					ack0 = 0x10
					ack1 = 0x0a
					ack2 = 0x00
					ack3 = 0x00
					tosend.append(round(((ack2 & 0x80)/8) + ((ack3 & 0x80)/4) + 0x0a)) # 4  0
					tosend.append(ack0 & 0x7f) # 5  1
					tosend.append(ack1 & 0x7f) # 6  2
					tosend.append(round(((ack0 & 0x80)/8) + ((ack1 & 0x80)/4) + 0x0a)) # 7  3
					tosend.append(ack2 & 0x7f) # 8  4
					tosend.append(ack3 & 0x7f) # 9  5
					tosend.append(0) # 10
					log.info(tosend.hex())
					bt.send(bytes(tosend))
					#bt.flush()
					clkhandled = 1
				if d.hex()[0:4] == "030c":
					# This is the ASCII message for the DGT3000
					asciimessage = ""
					for qi in range(2,11):
						asciimessage = asciimessage + chr(d[qi])
					widgets.write_text(13,asciimessage + "               ")
					#if d[12] > 0:
					#	board.beep(board.SOUND_GENERAL)
					tosend = bytearray(b'')
					tosend.append(DGT_BWTIME | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(10)
					ack0 = 0x10
					ack1 = 0x0c
					ack2 = 0x00
					ack3 = 0
					tosend.append(round(((ack2 & 0x80)/8) + ((ack3 & 0x80)/4) + 0x0a)) # 4  0
					tosend.append(ack0 & 0x7f) # 5  1
					tosend.append(ack1 & 0x7f) # 6  2
					tosend.append(round(((ack0 & 0x80)/8) + ((ack1 & 0x80)/4) + 0x0a)) # 7  3
					tosend.append(ack2 & 0x7f) # 8  4
					tosend.append(ack3 & 0x7f) # 9  5
					tosend.append(0) # 10
					log.info(tosend.hex())
					bt.send(bytes(tosend))
					#bt.flush()
					clkhandled = 1
				if d.hex()[0:4] == "030d":
					# This is the ASCII message for the revelation
					asciimessage = ""
					for qi in range(2,13):
						asciimessage = asciimessage + chr(d[qi])
					log.info("|||" + asciimessage + "||||")
					if "RevII" not in asciimessage and "PicoChs" not in asciimessage:
						widgets.write_text(13,asciimessage + "               ")
					#if d[13] > 0:
						#board.beep(board.SOUND_GENERAL)
					tosend = bytearray(b'')
					tosend.append(DGT_BWTIME | MESSAGE_BIT)
					tosend.append(0)
					tosend.append(10)
					ack0 = 0x10
					ack1 = 0x81
					ack2 = 0x00
					ack3 = 0
					tosend.append(round(((ack2 & 0x80)/8) + ((ack3 & 0x80)/4) + 0x0a)) # 4  0
					tosend.append(ack0 & 0x7f) # 5  1
					tosend.append(ack1 & 0x7f) # 6  2
					tosend.append(round(((ack0 & 0x80)/8) + ((ack1 & 0x80)/4) + 0x0a)) # 7  3
					tosend.append(ack2 & 0x7f) # 8  4
					tosend.append(ack3 & 0x7f) # 9  5
					tosend.append(0) # 10
					log.info(tosend.hex())
					bt.send(bytes(tosend))
					#bt.flush()
					clkhandled = 1
				if clkhandled == 0:
					log.info("Unhandled clock message " + d.hex())
				handled = 1
			if data[0] == DGT_SEND_CLK:
				# RabbitPlugin doesn't work without this so let's fake this for now
				if debugcmds == 1:
					log.info("DGT_SEND_CLK")
				sendClockData()
				handled = 1
			if data[0] == DGT_SEND_BATTERY_STATUS:
				# Ideally in the future we'll put a function in board to get the
				# battery status from the centaur. But for now, fake it!
				if debugcmds == 1:
					log.info("DGT_SEND_BATTERY_STATUS")
				tosend = bytearray(b'')
				tosend.append(DGT_BATTERY_STATUS | MESSAGE_BIT)
				tosend.append(0)
				tosend.append(12)
				tosend.append(100) # 100%
				tosend.append(0x7f)
				tosend.append(0x7f)
				tosend.append(0)
				tosend.append(0)
				tosend.append(0)
				tosend.append(0)
				tosend.append(0)
				tosend.append(0)
				bt.send(bytes(tosend))
				#bt.flush()
				handled = 1
			if handled == 0:
				log.info("Unhandled message type: " + str(data.hex()))
	except:
		# This indicates that the serial port connection has been broken
		dodie = 1
bt.close()
# Annoyingly this is needed to force a drop of the connection
os.system('sudo systemctl restart rfcomm')
widgets.write_text(0,'Disconnected')
