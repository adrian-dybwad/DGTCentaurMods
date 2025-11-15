# E-Paper Display Architecture

## Overview

The DGT Centaur Mods project has been refactored to use a unified, centralized e-paper display architecture. All display operations now go through a single `DisplayManager` class that provides a clean, consistent API.

## Architecture

### Core Components

1. **DisplayManager** (`display/display_manager.py`)
   - Singleton class managing all display operations
   - Automatic buffer management and update thread
   - Optimized partial and region-based updates
   - Thread-safe operations

2. **ChessBoardRenderer** (`display/chess_board_renderer.py`)
   - Renders chess boards from FEN strings or piece lists
   - Handles piece sprite loading and positioning
   - Supports board flipping for black's perspective

3. **HardwareDriver** (`display/hardware_driver.py`)
   - Wraps the C library (epaperDriver.so)
   - Handles image-to-buffer conversion
   - Provides display, partial update, and region update methods

4. **Display Types** (`display/display_types.py`)
   - Constants, enums, and type definitions
   - Color constants, dimensions, update modes
   - Battery levels, pin definitions, sprite offsets

### Legacy Compatibility

**epaper.py** provides backward compatibility by wrapping DisplayManager. Existing code using the old `epaper` module will continue to work, but new code should use `display_manager` directly.

## Usage

### Basic Usage

```python
from DGTCentaurMods.display.display_manager import display_manager

# Initialize display
display_manager.initialize()

# Draw text
display_manager.draw_text(row=2, text="Hello World")

# Draw chess board from FEN
display_manager.draw_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

# Clear screen
display_manager.clear()

# Shutdown
display_manager.shutdown()
```

### Advanced Features

```python
# Pause/resume updates for batch operations
display_manager.pause()
display_manager.draw_text(1, "Line 1")
display_manager.draw_text(2, "Line 2")
display_manager.draw_text(3, "Line 3")
display_manager.resume()

# Draw custom images
from PIL import Image
img = Image.new('1', (128, 20), 255)
# ... draw on img ...
display_manager.draw_image(x=0, y=40, image=img)

# Use special screens
display_manager.show_loading_screen()
display_manager.show_welcome_screen()
display_manager.show_standby_screen(show=True)
```

### Chess Board Rendering

```python
from DGTCentaurMods.display.chess_board_renderer import ChessBoardRenderer

renderer = ChessBoardRenderer()

# Render from FEN
board_image = renderer.render_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")

# Render from piece list
pieces = "rnbqkbnrpppppppp" + " " * 32 + "PPPPPPPPRNBQKBNR"
board_image = renderer.render_board(pieces)

# Flip for black's perspective
board_image = renderer.render_fen(fen, flip=True)
```

## Display Update Modes

The DisplayManager supports two update modes:

- **UpdateMode.PARTIAL** (default): Fast partial updates for quick refreshes
- **UpdateMode.FULL**: Full screen refresh for cleaner results

```python
from DGTCentaurMods.display.display_types import UpdateMode

display_manager.initialize(mode=UpdateMode.FULL)
# or
display_manager.set_update_mode(UpdateMode.PARTIAL)
```

## Thread Safety

All DisplayManager operations are thread-safe. The DisplayManager maintains an internal update thread that monitors the display buffer and automatically updates the physical display when changes are detected.

## Display States

The DisplayManager tracks its operational state:

- `UNINITIALIZED`: Not yet initialized
- `INITIALIZED`: Ready for operations
- `PAUSED`: Updates temporarily suspended
- `SLEEPING`: Display in low-power mode
- `DISABLED`: Drawing operations disabled

## Files Removed/Replaced

As part of the refactoring:

### Removed from board.py
- `initScreen()`, `clearScreen()`, `clearScreenBuffer()`, `sleepScreen()`
- `drawBoard()`, `writeText()`, `writeTextToBuffer()`
- `promotionOptionsToBuffer()`, `displayScreenBufferPartial()`
- Global variables: `screenbuffer`, `initialised`, `epd`

### Deleted Duplicates
- `tools/card-setup-tool/lib/epaper.py`
- `tools/card-setup-tool/lib/epd2in9d.py`
- `tools/card-setup-tool/lib/epdconfig.py`
- `DGTCentaurMods/opt/DGTCentaurMods/update/lib/epaper.py`
- `DGTCentaurMods/opt/DGTCentaurMods/update/lib/epd2in9d.py`
- `DGTCentaurMods/opt/DGTCentaurMods/update/lib/epdconfig.py`

### Compatibility Layer
- `display/epaper.py` - Now a thin wrapper over DisplayManager

## Migration Guide

### For New Code

Always use DisplayManager directly:

```python
from DGTCentaurMods.display.display_manager import display_manager

# NOT: from DGTCentaurMods.display import epaper
```

### For Existing Code

Existing code using `epaper` module will continue to work through the compatibility wrapper, but should be migrated to DisplayManager when possible.

## Benefits

1. **Single Source of Truth**: All display operations go through one manager
2. **No Race Conditions**: Thread-safe with single update thread
3. **Optimized Performance**: Region-based updates minimize refresh time
4. **Clean API**: Intuitive, well-documented methods
5. **Easy Testing**: Can run in headless mode for unit tests
6. **Type Safety**: Full type hints throughout
7. **Maintainability**: All display logic in one place

## Hardware Details

- **Display**: Waveshare 2.9" e-paper (128x296 pixels, 1-bit)
- **Driver IC**: IL0373 or compatible
- **Interface**: SPI via BCM GPIO pins
- **Update Time**: ~2 seconds full refresh, ~200ms partial update
- **Power**: Low-power with sleep mode support

## Troubleshooting

### Display not updating
- Check if display is paused: `display_manager.resume()`
- Verify initialization: `display_manager.state`
- Check logs for errors

### Ghosting or artifacts
- Try full refresh: `display_manager.set_update_mode(UpdateMode.FULL)`
- Clear display: `display_manager.clear()`

### Performance issues
- Use `pause()` / `resume()` for batch updates
- Prefer partial updates for small changes
- Check sleep counter timeout

## Future Enhancements

Possible improvements for future versions:

- Support for grayscale dithering
- Animation framework
- Custom font support
- Display rotation
- Multi-display support
- Web-based preview

