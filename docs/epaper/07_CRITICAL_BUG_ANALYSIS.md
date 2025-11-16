# CRITICAL BUG ANALYSIS: Menu Ghosting Root Cause

## IMMEDIATE FINDING: Counter Reset Logic Bug

### The Problem

**Line 165 in menu.py**: `self._partial_refresh_count = 0` resets counter in `draw()`

**Line 191 in menu.py**: When counter reaches limit, calls `self.draw()` which resets counter

**BUT**: `draw()` is also called on initial menu display (line 469), which is CORRECT.

### The REAL Bug

Looking at line 191-193:
```python
if self._partial_refresh_count >= self._max_partial_refreshes:
    self.draw(self.selected_index)  # This resets counter to 0 (line 165)
    service.submit_full(await_completion=True)
    self._partial_refresh_count = 0  # REDUNDANT - already reset in draw()
```

**ISSUE**: Counter is reset TWICE - once in `draw()` (line 165) and once explicitly (line 193).

**BUT MORE IMPORTANTLY**: The counter reset in `draw()` happens BEFORE the full refresh is submitted!

### The Sequence Bug

1. Counter reaches 8
2. `draw()` is called → counter reset to 0 (line 165)
3. `submit_full()` is called
4. Counter reset to 0 again (line 193) - redundant

**PROBLEM**: If `draw()` is called for ANY other reason (not just when counter reaches limit), counter resets prematurely!

### Investigation Needed

1. Is `draw()` called anywhere else besides initial display and counter limit?
2. Does the full refresh actually complete before counter is used again?
3. Is the counter being reset by something else?

---

## Agent 1 Strategy: Hardware Full Refresh Verification

**Focus**: Verify full refresh actually clears ghosting at hardware level

**Key Tests**:
1. Force full refresh every navigation (`_max_partial_refreshes = 1`)
2. Verify full refresh duration is 1.5-2.0s (not 0.4s)
3. Verify hardware busy signal during full refresh
4. Save framebuffer snapshot before full refresh and compare to display

**Expected Finding**: Full refresh may not be clearing ghosting (hardware issue) OR full refresh may not be sent (counter bug)

---

## Agent 2 Strategy: Framebuffer State Verification

**Focus**: Verify framebuffer contains correct content before refresh

**Key Tests**:
1. Log framebuffer state before/after menu drawing
2. Save framebuffer snapshot before each refresh
3. Compare framebuffer vs actual display
4. Verify menu area is cleared to white before drawing

**Expected Finding**: Framebuffer may have stale content OR framebuffer is correct but display is wrong

---

## Agent 3 Strategy: Counter Logic Deep Dive

**Focus**: Verify counter actually triggers full refreshes

**Key Tests**:
1. Log counter value at every increment/reset/check
2. Create timeline of counter state changes
3. Verify counter reaches 8 and triggers full refresh
4. Check if counter is reset prematurely

**Expected Finding**: Counter may not reach 8 OR counter reaches 8 but full refresh not triggered

---

## Agent 4 Strategy: Refresh Queue Analysis

**Focus**: Verify refreshes aren't being dropped or queued incorrectly

**Key Tests**:
1. Log every `submit_region()` and `submit_full()` call
2. Verify full refresh supersedes queued partials
3. Verify refresh queue doesn't accumulate
4. Verify `await_completion=True` actually waits

**Expected Finding**: Partial refreshes may be queued after full refresh OR full refresh may be dropped

---

## Agent 5 Strategy: Menu Drawing Artifact Analysis

**Focus**: Verify menu drawing doesn't leave artifacts

**Key Tests**:
1. Verify menu title is drawn and in framebuffer
2. Verify old selection is fully cleared
3. Verify regions cover all areas
4. Test: Explicitly clear menu area to white before drawing

**Expected Finding**: Menu title may not be drawn OR old selection may not be fully cleared

---

## IMMEDIATE ACTION REQUIRED

All 5 agents must investigate simultaneously. Each agent should add specific logging for their investigation and report findings with evidence.

**NO FIXES UNTIL ROOT CAUSE IS FOUND WITH EVIDENCE.**

