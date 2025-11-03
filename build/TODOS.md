TODOS:
Test promotion hardware feature, test and fix board text input feature.

## LED Pattern Summary

| Action | Pattern | Visual Effect |

|--------|---------|---------------|

| **Normal Shutdown** | h8→h1 cascade | LEDs light sequentially down the board |

| **Update Install** | All LEDs solid | All 8 LEDs lit at once |

| **Controller Sleep** | Single LED h8 | Only top-right LED |

| **Reboot** | h1→h8 cascade | LEDs light sequentially up the board |

## Files Modified

1. **DGTCentaurMods/opt/DGTCentaurMods/board/board.py**

                                                - Add `sleep_controller()` function
                                                - Improve `shutdown()` with LED cascade and better cleanup

2. **DGTCentaurMods/opt/DGTCentaurMods/menu.py**

                                                - Update shutdown handler (lines 817-820) with proper cleanup
                                                - (Optional) Add LED pattern to reboot handler

3. **DGTCentaurMods/opt/DGTCentaurMods/board/shutdown.py**

                                                - Simplify to call `board.sleep_controller()` OR
                                                - Delete if using direct function call in systemd

4. **DGTCentaurMods/etc/systemd/system/DGTStopController.service**

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
