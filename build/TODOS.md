TODOS:
Test promotion hardware feature, test and fix board text input feature.

## Draw/Resign Protocol Implementation

Currently, the back button menu in Universal mode allows resign/draw, but these only update the local database. The following needs to be investigated and implemented:

### Draw Request Flow
1. **Investigate**: How do Millennium, Pegasus, and Chessnut protocols handle draw offers?
2. **Implement offer/accept flow**:
   - Human presses Draw → send draw offer to connected app
   - Wait for app response (accept/decline)
   - If accepted → record draw in database
   - If declined → return to game with notification
3. **Handle incoming draw offers**: App offers draw → show prompt to human → send response

### Resign Signal
1. **Investigate**: How do Millennium, Pegasus, and Chessnut protocols signal resignation?
2. **Implement**: When human resigns, send appropriate protocol message to connected app
3. **Handle incoming**: If app/opponent resigns, update local state and database

### Affected Files
- `src/universalchess/universal.py` (orchestrator; game end actions live here and in `src/universalchess/managers/game/`)
- `src/universalchess/emulators/millennium.py`
- `src/universalchess/emulators/pegasus.py`
- `src/universalchess/emulators/chessnut.py`

### Notes
- For standalone engine mode (no app connected), immediate resign/draw is acceptable
- For relay mode (app connected), protocol-level messaging is required

## LED Pattern Summary

| Action | Pattern | Visual Effect |

|--------|---------|---------------|

| **Normal Shutdown** | h8→h1 cascade | LEDs light sequentially down the board |

| **Update Install** | All LEDs solid | All 8 LEDs lit at once |

| **Controller Sleep** | Single LED h8 | Only top-right LED |

| **Reboot** | h1→h8 cascade | LEDs light sequentially up the board |

## Files Modified

1. **src/universalchess/board/board.py**

                                                - Add `sleep_controller()` function
                                                - Improve `shutdown()` with LED cascade and better cleanup

2. **src/universalchess/universal.py**

                                                - Update shutdown handler (lines 817-820) with proper cleanup
                                                - (Optional) Add LED pattern to reboot handler

3. **src/universalchess/board/shutdown.py**

                                                - Simplify to call `board.sleep_controller()` OR
                                                - Delete if using direct function call in systemd

4. **packaging/deb-root/etc/systemd/system/DGTStopController.service**

                                                - Update to call `sleep_controller()` directly OR
                                                - Keep calling simplified shutdown.py

## Testing

1. **Test Normal Shutdown**

                                                - Navigate to Settings → Shutdown
                                                - Verify LED cascade pattern h8→h1
                                                - Verify "Shutting down" message displays
                                                - Verify system powers off cleanly

2. **Test Update Install Shutdown**

                                                - Place update .deb in `/tmp/dgtcentaurmods_armhf.deb`
                                                - Navigate to Settings → Shutdown
                                                - Verify all LEDs light up
                                                - Verify "Installing update" message

3. **Test Reboot**

                                                - Navigate to Settings → Reboot
                                                - Verify LED cascade pattern h1→h8 (if implemented)
                                                - Verify system reboots cleanly

4. **Test Controller Sleep on System Shutdown**

                                                - SSH into Pi and run `sudo poweroff`
                                                - Verify DGTStopController.service runs
                                                - Verify controller receives sleep command
                                                - Verify controller powers down with system

5. **Test Long Button Press Shutdown**

                                                - Hold PLAY button for long press
                                                - Verify automatic shutdown works
                                                - Verify LED patterns work from eventsThread
