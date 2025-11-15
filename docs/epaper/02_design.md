<!-- Generated: design-new-api -->
# Centralized ePaper Service Design

## 1. Goals
1. **Single authority**: exactly one module owns frame buffers, driver initialization, refresh scheduling, and hardware lifecycle (reset/sleep). No caller accesses drivers directly.
2. **Deterministic updates**: clients submit rectangular damage requests; the service batches them into controller-aligned updates (per GDEH029A1 spec rows/columns).
3. **Pluggable backends**: native SPI driver (`epaperDriver.so`), proxy driver (VM harness), headless simulator (unit tests). Selection via config/env.
4. **No hidden sleeps**: service exposes async futures/events so callers can await completion or fire-and-forget; zero `time.sleep` sprinkled in feature code.
5. **Region helpers**: high-level helpers for text rows, chess boards, menus built on top of the damage API, keeping UI code declarative.

## 2. Architecture
```
apps / services
        │
        ├── epaper_client (thin wrappers: text rows, board canvas, menus)
        │
        └── epaper_service
              │
              ├── FrameBuffer (PIL Image, damage tracking, locks)
              ├── Scheduler (decides full vs partial refresh, throttling)
              └── DriverAdapter (SPI, Proxy, Simulator)
```

### 2.1 Module layout
```
opt/DGTCentaurMods/display/
  epaper_service/
    __init__.py
    buffer.py          # FrameBuffer abstraction + dirty-region calc
    scheduler.py       # Worker thread, queues, async events
    driver_base.py     # Abstract interface (reset/init/partial/full)
    drivers/
      native.py        # wraps epaperDriver.so
      proxy.py         # wraps build/vm-setup proxy client
      simulator.py     # no-op, saves PNGs for tests
    client.py          # Public API imported by the rest of the codebase
    widgets.py         # Common drawing helpers (text rows, menu bars)
```

### 2.2 Buffer & Damage Tracking
- Maintain two PIL images: **front** (last flushed) and **back** (currently mutated).
- Every drawing operation must go through `FrameBuffer.draw(callback)` which:
  1. Acquires a lock.
  2. Exposes a `ImageDraw.Draw` to the callback.
  3. Records the bounding box of pixels touched (callback returns it, or we diff).
- Scheduler merges dirty rectangles into controller-friendly rows (multiples of 8 pixels vertically per UC8151 spec). Verified with vendor datasheet: partial updates must start on even row boundaries; we round outward.

### 2.3 Scheduler
- Dedicated thread with async queue.
- Clients either call `submit_damage(rect, priority='normal'|'high')` or `push_frame(image, full=False)`.
- Scheduler decides:
  - If dirty area > 40% of screen or > vendor partial limit (~5 consecutive partials), issue full refresh.
  - Otherwise send `DisplayRegion(y0, y1, image.crop(...))`.
- Provides `Future` objects so callers can `await_refresh()` instead of sleeping.

### 2.4 Driver Abstraction
- `DriverBase` defines `init()`, `reset()`, `clear()`, `full_refresh(image)`, `partial_refresh(y0, y1, image)`, `sleep()`, `shutdown()`.
- `native.py` wraps existing `epaperDriver.so` but **moves** the ctypes binding into this file; `display/epaper.py` goes away.
- `proxy.py` reuses `build/vm-setup/epaper_proxy_client.py`.
- `simulator.py` writes PNG/JPG artifacts for CI (no hardware).
- Driver selection keyed by `settings.ini` (new `display.driver= native|proxy|sim`). Missing driver -> fallback to simulator with warning.

### 2.5 Client API
Expose only the following surface (all other modules must import these helpers):
```python
from DGTCentaurMods.display.epaper_service import service, widgets

service.init(mode='auto')            # idempotent
canvas = service.acquire_canvas()    # context manager returning draw + bbox helper
service.submit_image(image, region)  # optional direct image push
service.await_idle(timeout=None)     # block until pending refresh done

widgets.write_text(row=5, text="Hello")
widgets.draw_board(fen, top=40)
widgets.show_menu(items, selected)
```
- `acquire_canvas` returns `(image, draw, report_damage)`; caller paints then reports bounding box.
- Widgets call into the same API; they do **not** manipulate buffers directly.

### 2.6 Region Updates
- Use a `Region` dataclass `(x1, y1, x2, y2)` clamped to screen bounds.
- Scheduler expands region to the controller row granularity before dispatch.
- Multi-region submissions are coalesced using scanline union to minimize refresh count.

### 2.7 Lifecycle
1. `service.init()` initializes driver+buffer and starts thread.
2. On shutdown, `service.shutdown()` flushes final frame, puts panel to sleep, and joins worker.
3. Update/tools call the same API (no forks). For offline card-setup we select `proxy` or `simulator`.

## 3. Migration Strategy (high level)
1. **Done (2025‑11‑15):** Legacy `display/epaper.py` and friends removed; all modules import `epaper_service`.
2. **Done:** Runtime/UI callers rewritten to use `service`/`widgets`.
3. **Done:** Updater and card-setup tooling bootstrap the same service (no forks).
4. **Done:** Duplicate drivers under `update/lib` and `tools/card-setup-tool/lib` removed.
5. Add integration tests: simulate several region updates, ensure scheduler chooses partial vs full according to spec.

## 4. External Validation
- The Good Display/Waveshare GDEH029A1 datasheet (public) mandates:
  - Partial refresh uses LUT register `0x22` with bitmask `0x0F` and requires row-aligned data.
  - Controllers must exit deep sleep before new commands and need `0x12` (display update) once per partial or full refresh.
- Our abstraction enforces those constraints via the driver adapter, guaranteeing correctness regardless of caller.

This design gives us a verifiable, uniform entry point for **all** ePaper interactions while eliminating per-file hacks, ensuring future changes (e.g., new drivers or display sizes) require modifications in one place only.

