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
| `opt/DGTCentaurMods/display/epaper.py` | Primary runtime driver wrapper. Maintains global `epaperbuffer`, spawns an update thread, decides between `DisplayPartial` vs `DisplayRegion`. | Mixed responsibilities (buffer management, drawing helpers, menu rendering). Uses globals for thread life-cycle; no locking; writes static JPG side-effect. |
| `opt/DGTCentaurMods/display/epaper_driver.py` | Thin ctypes bridge to `epaperDriver.so`. Exposes `display`, `DisplayPartial`, `DisplayRegion`, `sleepDisplay`, `powerOffDisplay`. | No error handling; automatically loads shared object and opens hardware during import; no abstraction for alternative backends (proxy, simulator). |
| `opt/DGTCentaurMods/display/epd2in9d.py` | Legacy Waveshare-style Python driver (SPI bit-banging). | Mostly unused directly but still imported by some tools; duplicates reset/command timings. |
| `opt/DGTCentaurMods/update/lib/epaper.py` | Copy of the runtime driver for the on-device updater. | Diverges (uses `epd2in9d` directly instead of `epaper_driver.py`), lacks region diffing, uses blocking `display()` for every frame (slow). |
| `tools/card-setup-tool/lib/epaper.py` | Another copy for the SD-card/first-boot tooling. | Same issues as update-version; no logging; thread never joins; sleeps baked in. |
| `build/vm-setup/epaper_proxy_{server,client,wrapper}.py` | Test/proxy driver for VM harness. | Reimplements `epaperDriver` semantics but only for dev workflow; not integrated with runtime selection logic. |

## 3. Direct Usage Sites
The following modules import `DGTCentaurMods.display.epaper` directly and manipulate globals/drawing primitives:
- Runtime/game logic: `opt/DGTCentaurMods/game/gamemanager.py`, `opt/DGTCentaurMods/games/manager.py`, both `.../game/uci.py`, `.../games/uci.py`, `game/1v1Analysis.py`, `menu.py`, `ui/epaper_menu.py`, `ui/simple_text_input.py`, `board/board.py`.
- Background services: `scripts/update.sh` indirectly when launching update module, `update/update.py`, `update/lib/*.py`.
- Tooling: everything under `tools/card-setup-tool/lib/`, several scripts in `build/vm-setup`, plus developer probes in `tools/dev-tools/*probe*.py`.

Each file makes assumptions about:
1. Whether the update thread is currently paused.
2. Whether `epaperbuffer` can be mutated without locking.
3. How to trigger partial updates (`drawImagePartial`, `drawWindow`, manual driver calls).
4. Arbitrary `time.sleep` delays the author sprinkled to “wait for refresh”.

## 4. Deficiencies
- **No central API contract**: call sites freely mix `driver.DisplayRegion`, `epaper.drawImagePartial`, direct buffer writes, or `epaper_driver.display`.
- **Thread-safety**: no locks; two callers can mutate `epaperbuffer` while the update thread copies it, resulting in torn frames.
- **No capability detection**: hardware vs proxy vs simulator vs updater all require different init sequences yet rely on implicit side effects at import time.
- **Partial-update math**: `compute_changed_region` in `display/epaper.py` tries to diff byte arrays but assumes 16 bytes per row — contradicting the datasheet (actually 16 bytes per 128-px row, so this is mostly correct but it ignores controller row-alignment requirements). Other copies skip diffing entirely.
- **Redundant copies**: at least three forks of the same driver logic (`display/epaper.py`, `update/lib/epaper.py`, `tools/card-setup-tool/lib/epaper.py`) have drifted, making bug fixes inconsistent.
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

