# E-paper Framework Multi-agent Log

## Stage 1 – Architecture Outline

**Agent1 proposal**

- Build a self-contained `epaper` package with modules: `regions`, `framebuffer`, `scheduler`, `driver`, `widgets`, and `controller`.
- Keep responsibilities clear: region math and dirty tracking stay isolated from rendering, scheduling, and panel IO.
- Run everything through `EPaperController`, which owns widgets, the framebuffer, diffing, and refresh planning.

**Agent2 review**

- Agrees with modular split but requests that the controller never depend on resources outside the package and that every public class carry explicit docstrings explaining assumptions.
- Adds requirement for `RefreshPlan` objects so tests can assert scheduler behavior cleanly.

**Consensus**

- Proceed with the module list above and document every class/function.

## Stage 2 – Widget Model and Canvas API

**Agent1 proposal**

- Create an abstract `Widget` base class with async hooks: `tick(timestamp)` and `render(canvas)`.
- Provide a `WidgetCanvas` wrapper that clamps drawing to the widget bounds while delegating to the framebuffer.
- Widgets raise `mark_dirty()` when they mutate state; controller reads `widget.is_dirty`.

**Agent2 review**

- Requests region-aware draw helpers (`fill`, `draw_rect`, `draw_text`) and a simple bitmap font so demos do not require external assets.
- Emphasizes that `render` must be awaited even for simple widgets to remain consistent with the "prefer async" rule.

**Consensus**

- Implement `Widget` with dirty tracking plus a `CanvasView` exposing `fill`, `draw_rect`, and `draw_text` (using a built-in 5×3 font scaled by callers).

## Stage 3 – Scheduler and Driver Interaction

**Agent1 proposal**

- `AdaptiveRefreshPlanner` tracks partial budget, promotes full refresh after either elapsed time or budget exhaustion, and limits region count via merging.
- `EPaperDriver` defines async `refresh(plan, frame)`; provide a `SimulatedDriver` for demos/tests that records refreshes.

**Agent2 review**

- Requests explicit `RefreshMode` enum with modes `FULL`, `PARTIAL_FAST`, `PARTIAL_BALANCED`. Planner should choose `PARTIAL_FAST` when widgets request fast updates.
- Driver should expose async `connect()`/`close()` no-ops for extensibility.

**Consensus**

- Implement enum with three modes, include optional `fast_hint` argument in planner, and add optional lifecycle hooks in `EPaperDriver`.

## Stage 4 – Demo Scenario

**Agent1 proposal**

- Provide `epaper_demo.py` that instantiates controller + simulated driver, registers `ClockWidget`, `BatteryWidget`, and `MessageWidget`.
- Clock ticks every ~1 second, battery every ~15 seconds, message every 5 seconds.

**Agent2 review**

- Wants the demo to run for a fixed duration (e.g., 30 seconds) and log refresh summaries rather than drawing to real hardware.

**Consensus**

- Write the demo as an asyncio program running 30 seconds, printing refresh details gathered from the simulated driver.


