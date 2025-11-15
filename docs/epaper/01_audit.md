<!-- Generated: audit-drivers -->
# ePaper Driver & Usage Audit

## 1. Hardware & Vendor Constraints (external verification)
- The Centaur’s 2.9" display is a Good Display/Waveshare GDEH029A1-class panel (serial bus, UC8151 controller). Vendor documentation specifies:
  - Full refresh latency ≈ 1.5–2.0 s, partial refresh ≈ 260–300 ms when the correct LUT is used.
  - The controller requires region-specific updates to be aligned to byte rows (per the 0x44/0x45 register semantics), otherwise the entire screen refreshes.
  - Deep-sleep must only be entered after power-save commands and should be exited with a reset + panel-on sequence.
- None of the existing drivers enforce those timing or alignment guarantees, so data races easily produce ghosting or watchdog resets.

## 2. Driver Implementations
| Location | Purpose | Notes |
| --- | --- | --- |
| ~~`opt/DGTCentaurMods/display/epaper.py`~~ | Legacy runtime wrapper (removed). | Superseded by `display.epaper_service` on 2025‑11‑15; responsibilities split between `FrameBuffer`, `RefreshScheduler`, and `widgets`. |
| ~~`opt/DGTCentaurMods/display/epaper_driver.py`~~ | Legacy ctypes bridge (removed). | Native access now lives in `display/epaper_service/drivers/native.py` with proper dependency injection. |
| ~~`opt/DGTCentaurMods/display/epd2in9d.py`~~ | Waveshare reference driver (removed). | Eliminated to avoid parallel code paths; the shared object `epaperDriver.so` is consumed exclusively by the native driver wrapper. |
| ~~`opt/DGTCentaurMods/update/lib/epaper.py`~~ | Stand-alone updater copy (removed). | Updater now imports the primary `epaper_service` directly, so no forked driver code remains. |
| ~~`tools/card-setup-tool/lib/epaper.py`~~ | SD-card/first-boot copy (removed). | First-boot utility dynamically extracts the release `.deb` and reuses the real service implementation. |
| `build/vm-setup/epaper_proxy_{server,client,wrapper}.py` | VM proxy harness. | Server now calls `epaper_service`, wrapper simply exports `EPAPER_DRIVER=proxy`, and the client continues to forward image payloads. |

## 3. Direct Usage Sites
All runtime, service, tooling, and UI modules now depend on `display.epaper_service` exclusively. This section is retained for historical context; prior to 2025‑11‑15 the files listed below mutated `epaperbuffer` directly and made incompatible driver calls:
- Runtime/game logic (`game/gamemanager.py`, `games/manager.py`, `game/uci.py`, `games/uci.py`, `game/1v1Analysis.py`, `menu.py`, `ui/epaper_menu.py`, `ui/simple_text_input.py`, `board/board.py`).
- Background services (`scripts/update.sh`, `update/update.py`, legacy `update/lib/*.py`).
- Tooling (`tools/card-setup-tool/lib`, `build/vm-setup/*`, developer probes).

When those modules were coupled to the legacy driver they made assumptions about:
1. Whether the update thread is currently paused.
2. Whether `epaperbuffer` can be mutated without locking.
3. How to trigger partial updates (`drawImagePartial`, `drawWindow`, manual driver calls).
4. Arbitrary `time.sleep` delays the author sprinkled to “wait for refresh”.

## 4. Deficiencies
- **No central API contract**: legacy call sites mixed `driver.DisplayRegion`, `epaper.drawImagePartial`, direct buffer writes, or `epaper_driver.display`. The unified service eliminates these entry points.
- **Thread-safety**: no locks; two callers can mutate `epaperbuffer` while the update thread copies it, resulting in torn frames.
- **No capability detection**: hardware vs proxy vs simulator vs updater all require different init sequences yet rely on implicit side effects at import time.
- **Partial-update math**: `compute_changed_region` in `display/epaper.py` tries to diff byte arrays but assumes 16 bytes per row — contradicting the datasheet (actually 16 bytes per 128-px row, so this is mostly correct but it ignores controller row-alignment requirements). Other copies skip diffing entirely.
- **Redundant copies**: at least three forks of the same driver logic (`display/epaper.py`, `update/lib/epaper.py`, `tools/card-setup-tool/lib/epaper.py`) have drifted, making bug fixes inconsistent. _Resolved: all copies removed and replaced with the centralized service._
- **Blocking sleeps**: dozens of modules call `time.sleep` after draw calls “to let the screen update”, which actually slows down refresh and defeats the diffing thread.
- **No instrumentation**: cannot measure refresh latency or detect missed frames because there is no central logger/metrics surface.

## 5. Opportunities for Refactor
- Introduce a single ePaper service (async-safe) that owns:
  - Buffer diffing with proper row alignment.
  - Partial/full refresh scheduling based on damage rectangles provided by clients.
  - Driver backend selection (native SPI, proxy server, future simulators) via config setting.
  - Declarative drawing API (submit Pillow image or declarative widgets) so caller code does not manipulate globals.
- Provide thin client helpers for common patterns (text rows, board render, promotion menu) that call into the service instead of re-implementing drawing.
- Replace ad-hoc sleeps with futures/promises or callbacks once the hardware signals refresh complete.

This audit confirms the entire project currently lacks a standardized, verifiable approach to driving the ePaper panel. The next steps are to design and implement the centralized service, then migrate every caller (runtime and tooling) to it without backward-compatibility shims.

