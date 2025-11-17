# EPaper Framework Implementation Guide

## Original Instructions (Clarified)

### Task
Create a completely new, self-contained ePaper display framework from scratch. This framework should replace the existing problematic display system with a clean, widget-based architecture.

### Requirements

1. **Widget-Based Architecture**:
   - Widgets implement ONLY content rendering (via `render()` method)
   - Framework handles ALL display concerns:
     - Region tracking and dirty detection
     - Region merging and optimization
     - Controller alignment (8-pixel rows)
     - Refresh scheduling (partial vs full)
     - Hardware communication
   - Widgets should NOT worry about:
     - Where to refresh
     - When to refresh
     - How regions are merged
     - Display driver details

2. **Self-Contained**:
   - All code in `epaper/` folder
   - All resources (including `epaperDriver.so`) in `epaper/` folder
   - No imports from existing `display/epaper_service/` code
   - Can reference existing code for understanding, but implement fresh

3. **Real Hardware Support**:
   - Must work on actual hardware using native driver
   - Use `epaperDriver.so` from `epaper/` folder
   - Support simulator mode for testing (saves PNGs)

4. **Automatic Region Management**:
   - Use shadow framebuffer pattern (current vs flushed)
   - Automatic dirty region detection via image diffing
   - Merge overlapping/adjacent regions automatically
   - Expand to controller requirements (8-pixel rows, full-width due to API)
   - Only refresh what actually changed

5. **Demo Application** (`epaper_demo.py`):
   - 24 pixel high clock (updates every second)
   - Fake battery meter (cycles through levels)
   - Text that changes every 5 seconds
   - Bouncing ball that:
     - Appears on top of text (not underneath)
     - Doesn't leave trails when moving
     - Works in empty areas (top/bottom of screen)
   - Screen filled with text widgets

### Key Design Principles

- **Separation of Concerns**: Widgets = content, Framework = display logic
- **Automatic Optimization**: Framework handles all efficiency concerns
- **Industry Standards**: Follow ePaper best practices (periodic full refreshes, etc.)
- **No Legacy Code**: Start fresh, don't import problems from old system

## Architecture Overview

The framework implements a widget-based system where widgets are pure content renderers, and the framework handles all display management automatically.

### Core Components

```
epaper/
├── __init__.py              # Public API (DisplayManager)
├── display_manager.py        # Main coordinator
├── widget.py                # Base widget class
├── framebuffer.py           # Shadow buffer with diff tracking
├── regions.py                # Region management and merging
├── refresh_scheduler.py      # Refresh queue and execution
├── driver.py                 # Native hardware driver wrapper
├── simulator_driver.py       # Simulator for testing
├── epaperDriver.so          # Native C library (hardware)
└── widgets/                  # Example widgets
    ├── __init__.py
    ├── clock.py
    ├── battery.py
    ├── text.py
    └── ball.py
```

### Design Principles

1. **Widgets are content-only**: Widgets implement `render()` method that returns a PIL Image. They don't worry about regions, refresh logic, or display handling.

2. **Automatic dirty tracking**: Framebuffer uses image diffing (comparing current vs flushed buffer) to automatically detect what changed.

3. **Region merging**: Overlapping or adjacent regions are automatically merged to minimize refresh operations.

4. **Controller alignment**: Regions are expanded to 8-pixel row boundaries (UC8151 requirement) and full-width rows (C library API requirement).

5. **Smart refresh scheduling**: 
   - Partial refreshes for small changes
   - Full refreshes after N partials to prevent ghosting
   - Automatic throttling to prevent display overload

## Implementation Details

### 1. Widget System

**Base Widget Class** (`widget.py`):
- Widgets have position (x, y) and size (width, height)
- Implement `render()` method returning PIL Image in mode "1" (1-bit monochrome)
- Framework automatically tracks widget positions and detects changes

**Example Widget**:
```python
class ClockWidget(Widget):
    def __init__(self, x: int, y: int, height: int = 24):
        super().__init__(x, y, width=80, height=height)
    
    def render(self) -> Image.Image:
        image = Image.new("1", (self.width, self.height), 255)
        # Draw clock content...
        return image
```

**Moving Widgets** (like ball):
- Implement `get_previous_region()` method to track old position
- Implement `get_mask()` method for compositing (so widget appears on top)
- Framework automatically clears old position and renders new position

### 2. Framebuffer with Diff Tracking

**Shadow Buffer Pattern**:
- `_current`: Working buffer (what widgets draw to)
- `_flushed`: Last known state on display (what was successfully refreshed)

**Dirty Region Detection**:
- Scans in 8x8 blocks (matches controller row alignment)
- Compares pixel data between current and flushed buffers
- Returns list of changed regions

**Flush Tracking**:
- After successful hardware refresh, `flush_region()` copies current → flushed
- This ensures accurate diffing on next update

### 3. Region Management

**Region Class**:
- Immutable dataclass with (x1, y1, x2, y2) - inclusive start, exclusive end
- Methods: `clamp()`, `union()`, `intersects()`, `width()`, `height()`

**Region Merging**:
- Merges overlapping regions vertically
- Merges adjacent regions within 8 pixels (threshold)
- Reduces number of refresh operations

**Controller Alignment**:
- Vertically: Expands to 8-pixel row boundaries (UC8151 controller requirement)
- Horizontally: Expands to full width (C library `displayRegion()` API limitation)
  - The C library's `displayRegion(y0, y1, image)` function only takes y coordinates
  - It always refreshes full-width rows for the specified y range
  - This is an API limitation, not necessarily a controller limitation
  - **Important**: Even if only a small widget (like a ball) moves, the entire width of those rows is refreshed
  - We still optimize by only refreshing necessary rows vertically (not the entire screen)
  - Example: A 12-pixel ball moving vertically will refresh full-width rows (128 pixels wide) for the affected rows

### 4. Refresh Scheduler

**Queue-based System**:
- Background thread processes refresh requests
- Futures allow async/await pattern (no blocking sleeps)
- Full refreshes supersede queued partials

**Refresh Decision Logic**:
- Full refresh if:
  - Explicitly requested
  - Partial refresh count >= max (default: 50, configurable)
  - More than 5 minutes since last full refresh
- Partial refresh otherwise

**Ghosting Prevention**:
- Industry standard: Full refresh every 8-10 partial refreshes
- Default is 50 to allow more partial refreshes, but can be reduced for fast-moving content
- For fast-moving content (like bouncing ball): Consider reducing to 3-5 partial refreshes
- Can add rapid-update detection logic to force full refreshes more frequently when needed

**Throttling**:
- Minimum 100ms between refreshes (prevents display overload)
- Scheduler queues requests and processes in batches

### 5. Display Manager

**Widget Lifecycle**:
- `add_widget()`: Add widget to display
- `remove_widget()`: Remove and clear widget region
- `update()`: Render all widgets, detect changes, schedule refreshes

**Rendering Order**:
1. Render static widgets first
2. Clear old positions of moving widgets (re-render static widgets there)
3. Render moving widgets last (so they appear on top)

**Compositing**:
- Widgets with `get_mask()` method use mask compositing
- Allows widgets to appear on top without overwriting background
- Mask: white (255) = paste, black (0) = keep existing

### 6. Driver Interface

**Native Driver** (`driver.py`):
- Wraps `epaperDriver.so` C library
- Handles SPI communication with UC8151 controller
- Converts PIL Images to byte format expected by hardware

**Byte Conversion**:
- Row-major order
- 8 pixels per byte, MSB first (left to right)
- Formula: `byte_index = y * bytes_per_row + (x // 8)`
- Buffer size: `(width + 7) // 8 * height` bytes

**Refresh Methods**:
- `full_refresh(image)`: Full screen (1.5-2.0s typical)
- `partial_refresh(y0, y1, image)`: Partial rows (260-300ms typical)
- Image is rotated 180° to match hardware orientation

**Important**: The C library's `displayRegion()` function only takes y0, y1 coordinates (row range), not x coordinates. This means it always refreshes full-width rows for the specified y range. This is an API limitation, not a controller limitation.

**Note**: The library also contains a `displayPartial()` function that is not currently used. This function may support x/y coordinates for true partial-width refreshes. To use it, you would need to:
1. Determine its function signature (likely `displayPartial(x1, y1, x2, y2, image_data)` or similar)
2. Update the driver to use `displayPartial()` instead of `displayRegion()`
3. Modify `expand_to_controller_alignment()` to only expand vertically, not horizontally
4. Test to ensure it works correctly with the hardware

## Key Learnings and Fixes

### Critical Bugs Fixed

1. **Byte Index Calculation** (driver.py):
   - **Issue**: Original formula `int((x + y * width) / 8)` was incorrect for row-major order
   - **Fix**: `y * bytes_per_row + (x // 8)` with proper bytes_per_row calculation
   - **Impact**: Would cause incorrect pixel data to be sent to hardware

2. **Max Partial Refreshes** (refresh_scheduler.py):
   - **Default**: 50 (allows many partial refreshes)
   - **For fast-moving content**: Should be reduced to 3-5 to prevent ghosting
   - **Industry standard**: 8-10 partial refreshes before full refresh
   - **Note**: Can be adjusted based on content type and update frequency

3. **Shutdown Recursion** (display_manager.py):
   - **Issue**: `shutdown()` called `update()`, which triggered signal handlers during PIL operations
   - **Fix**: Added `_shutting_down` flag, removed `update()` call from shutdown
   - **Impact**: Prevents recursive signal handler calls and timeouts

### Important Discoveries

4. **LED Light Interference**:
   - **Discovery**: Strong LED lights (iPhone flashlights, etc.) can affect ePaper displays during refresh
   - **Cause**: EPaper displays use light-sensitive particles that can be influenced by bright light during the refresh process
   - **Symptom**: Fading or ghosting artifacts that appear to be code-related but are actually environmental
   - **Solution**: Avoid shining bright lights directly on the display during updates
   - **Note**: This is a physical property of ePaper technology, not a software bug

### Design Decisions

1. **Full-Width Row Requirement**:
   - The C library API requires full-width rows (not a controller limitation)
   - We still optimize by only refreshing necessary rows vertically
   - This is the best we can do given the API constraints

2. **Widget Rendering Order**:
   - Static widgets render first
   - Moving widgets render last (on top)
   - Old positions are cleared by re-rendering static widgets

3. **Mask Compositing**:
   - Used for widgets that need to appear on top (like ball)
   - Prevents overwriting background unnecessarily
   - Only ball pixels are pasted, background stays visible

4. **Dirty Region Detection**:
   - Uses 8x8 block scanning (matches controller alignment)
   - Compares pixel data between current and flushed buffers
   - More efficient than pixel-by-pixel comparison

## Usage Example

```python
from epaper import DisplayManager
from epaper.widgets import ClockWidget, BatteryWidget, TextWidget, BallWidget

# Create display manager
display = DisplayManager()
display.init()

# Create widgets
clock = ClockWidget(x=0, y=0, height=24)
battery = BatteryWidget(x=98, y=6, width=30, height=12)
ball = BallWidget(x=64, y=150, radius=6)
text = TextWidget(x=0, y=30, width=128, height=40, text="Hello")

# Add widgets (ball last so it appears on top)
display.add_widget(clock)
display.add_widget(battery)
display.add_widget(text)
display.add_widget(ball)

# Initial full refresh
display.update(force_full=True)

# Main loop
while True:
    # Update widget state
    ball.set_position(new_x, new_y)
    battery.set_level(new_level)
    
    # Framework handles everything else
    display.update()
    time.sleep(0.1)

# Cleanup
display.shutdown()
```

## Best Practices

1. **Widget Design**:
   - Keep `render()` method fast (no blocking operations)
   - Return images in mode "1" (1-bit monochrome)
   - Ensure image size matches widget dimensions

2. **Update Frequency**:
   - For fast-moving content, consider reducing update rate
   - Or reduce `_max_partial_refreshes` to force more full refreshes
   - Balance between responsiveness and ghosting

3. **Shutdown**:
   - Always call `shutdown()` to properly clean up
   - Don't call `update()` during shutdown
   - Handle exceptions in shutdown gracefully

4. **Region Optimization**:
   - Framework automatically merges and optimizes regions
   - Don't manually manage regions - let the framework handle it
   - Widgets should only worry about content

5. **Ghosting Prevention**:
   - Use appropriate `_max_partial_refreshes` for content type
   - Static content: 8-10 partials is fine (default 50 also works)
   - Fast-moving content: Reduce to 3-5 partials to prevent ghosting
   - Consider time-based full refresh triggers for rapid updates
   - If experiencing ghosting, reduce `_max_partial_refreshes` in RefreshScheduler

## Hardware Constraints

1. **UC8151 Controller**:
   - Requires 8-pixel row alignment for partial refreshes
   - Full refresh: ~1.5-2.0 seconds
   - Partial refresh: ~260-300ms (with correct LUT)

2. **C Library API**:
   - `displayRegion(y0, y1, image)` only takes y coordinates
   - Always refreshes full-width rows
   - Image width determines refresh width (but API doesn't support x offset)

3. **Display Dimensions**:
   - Width: 128 pixels
   - Height: 296 pixels
   - 1-bit monochrome (black/white)

## Testing

**Simulator Mode**:
```python
display.init(use_simulator=True)
# Or set environment variable:
# EPAPER_SIMULATOR=true python3 epaper_demo.py
```

Simulator saves PNG files to `/tmp/epaper-sim/` instead of updating hardware.

## Troubleshooting

**Ghosting/Fading Issues**:
- **LED Light Interference**: Strong LED lights (like iPhone flashlights) can affect ePaper displays during refresh, causing fading or ghosting artifacts. This is because ePaper displays use light-sensitive particles that can be influenced by bright light during the refresh process. Avoid shining bright lights directly on the display during updates.
- Reduce `_max_partial_refreshes` in RefreshScheduler (try 3-5 for fast content)
- Add rapid-update detection logic if needed
- Increase time between updates in application
- Ensure full refreshes are happening regularly (check `_max_partial_refreshes` value)

**Shutdown Hangs**:
- Ensure `_shutting_down` flag prevents recursive calls
- Don't call `update()` during shutdown
- Scheduler should cancel pending requests on stop

**Incorrect Display**:
- Verify byte conversion formula is correct
- Check image rotation (180° for hardware orientation)
- Ensure regions are properly expanded to controller alignment

**Full-Width Row Refreshes**:
- **Expected Behavior**: When any widget changes, the entire width of the affected rows is refreshed (not just the widget area)
- **Cause**: C library API limitation - `displayRegion()` only takes y coordinates, not x coordinates
- **Impact**: Small moving widgets (like a ball) will refresh full-width rows, which may be visible during refresh
- **Optimization**: Only the necessary rows are refreshed vertically (8-pixel aligned), not the entire screen
- **Note**: This is a hardware/API limitation, not a framework bug. The framework correctly identifies only the changed rows.
- **Potential Solution**: The library contains an unused `displayPartial()` function that may support x/y coordinates. See "Driver Interface" section for details.

## Implementation Checklist

When implementing this framework from scratch, ensure:

- [ ] Widget base class with `render()` method
- [ ] Framebuffer with current/flushed shadow buffers
- [ ] Automatic dirty region detection (image diffing)
- [ ] Region merging for overlapping/adjacent regions
- [ ] Controller alignment expansion (8-pixel rows, full-width)
- [ ] Refresh scheduler with queue and background thread
- [ ] Native driver wrapper for `epaperDriver.so`
- [ ] Simulator driver for testing
- [ ] Display manager coordinating all components
- [ ] Proper shutdown handling (no recursion)
- [ ] Ghosting prevention (periodic full refreshes)
- [ ] Moving widget support (ball with mask compositing)
- [ ] All resources in `epaper/` folder
- [ ] Demo application showcasing features

## Critical Implementation Notes

1. **Byte Conversion**: Must use correct row-major formula:
   ```python
   bytes_per_row = (width + 7) // 8
   byte_index = y * bytes_per_row + (x // 8)
   ```

2. **Region Expansion**: Always expand to full-width rows due to C library API limitation

3. **Ghosting Prevention**: Adjust `_max_partial_refreshes` based on content:
   - Static content: 50 (default) or 8-10
   - Fast-moving content: 3-5

4. **Shutdown**: Never call `update()` during shutdown to prevent recursion

5. **Widget Order**: Add moving widgets last so they render on top

## Future Improvements

1. **Adaptive Refresh Strategy**:
   - Detect content movement speed
   - Automatically adjust partial/full refresh ratio
   - Dynamic `_max_partial_refreshes` based on update frequency

2. **Region Optimization**:
   - If C library API is updated to support x coordinates, optimize horizontal refresh
   - Currently limited by API, not controller capability

3. **Widget Layering**:
   - Add explicit z-order support
   - More sophisticated compositing options

4. **Performance**:
   - Optimize dirty region detection (currently 8x8 blocks)
   - Consider spatial indexing for faster region merging
   - Cache widget renders when unchanged

## Quick Reference

### File Structure
```
epaper/
├── __init__.py              # DisplayManager export
├── display_manager.py        # Main coordinator (widgets, framebuffer, scheduler)
├── widget.py                # Base widget class
├── framebuffer.py           # Shadow buffer with diff tracking
├── regions.py                # Region class, merging, alignment
├── refresh_scheduler.py      # Background refresh queue
├── driver.py                 # Native hardware driver
├── simulator_driver.py       # Simulator for testing
├── epaperDriver.so          # Native C library
└── widgets/                  # Example widgets
    ├── clock.py
    ├── battery.py
    ├── text.py
    └── ball.py
```

### Key Classes

- **DisplayManager**: Main entry point, coordinates everything
- **Widget**: Base class - implement `render()` method
- **FrameBuffer**: Shadow buffers, dirty region detection
- **RefreshScheduler**: Background thread, refresh queue
- **Driver**: Hardware interface (native or simulator)

### Common Patterns

**Creating a Widget**:
```python
class MyWidget(Widget):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
    
    def render(self) -> Image.Image:
        image = Image.new("1", (self.width, self.height), 255)
        # Draw content...
        return image
```

**Using the Framework**:
```python
display = DisplayManager()
display.init()
display.add_widget(my_widget)
display.update()  # Framework handles everything
display.shutdown()
```

### Important Constants

- Display size: 128×296 pixels
- Row alignment: 8 pixels (UC8151 requirement)
- Full refresh: ~1.5-2.0 seconds
- Partial refresh: ~260-300ms
- Max partial refreshes: 50 (default), 3-5 for fast content

