# 5-Agent Ghosting Investigation Plan
## Root Cause Analysis for Persistent Menu Fading Issue

**Problem**: Menu navigation causes non-active items to fade. Menu title disappears. Chess board renders faintly. Gets worse with each navigation.

**Critical**: NO GUESSING - Systematic investigation only.

---

## Agent 1: Hardware/Driver Full Refresh Verification

### Strategy: Verify Full Refresh Actually Clears Ghosting at Hardware Level

### Investigation Tasks:

1. **Verify full refresh is actually being sent to hardware**
   - Add logging to verify `driver.full_refresh()` is called when counter reaches limit
   - Log the actual image being sent (save snapshot before refresh)
   - Verify `_wait_for_idle()` completes successfully (hardware actually finished)

2. **Verify full refresh duration matches expected 1.5-2.0s**
   - Current logs show duration - verify it's actually 1.5-2.0s, not 0.4s
   - If duration is too short, hardware may not be doing full refresh
   - Check if `display()` C function is actually sending full refresh command

3. **Verify hardware busy signal during full refresh**
   - Log `readBusy()` values throughout full refresh cycle
   - Verify hardware goes busy → idle (proves refresh happened)
   - If hardware never goes busy, refresh command may not be sent

4. **Test: Force full refresh after every navigation**
   - Temporarily set `_max_partial_refreshes = 1` to force full refresh every time
   - If ghosting still occurs, full refresh is NOT clearing ghosting (hardware issue)
   - If ghosting stops, counter logic is the problem

5. **Verify framebuffer content before full refresh**
   - Save framebuffer snapshot before each full refresh
   - Compare snapshots - if framebuffer is correct but display shows ghosting, hardware issue
   - If framebuffer has artifacts, drawing logic issue

### Expected Findings:
- Full refresh may not be clearing ghosting (hardware/driver issue)
- Full refresh may not be sent (counter logic issue)
- Full refresh may be too fast (wrong command sent)

---

## Agent 2: Framebuffer State Verification

### Strategy: Verify Framebuffer Contains Correct Content Before Refresh

### Investigation Tasks:

1. **Verify framebuffer is cleared before menu drawing**
   - Log framebuffer state before `MenuRenderer.draw()` is called
   - Verify menu area is white (255) before drawing
   - If framebuffer has old content, clearing logic is broken

2. **Verify framebuffer after menu drawing**
   - Log framebuffer state after `MenuRenderer.draw()` completes
   - Verify all menu elements are drawn correctly in framebuffer
   - Save framebuffer snapshot and visually inspect

3. **Verify framebuffer during selection change**
   - Log framebuffer before and after `change_selection()`
   - Verify old selection is cleared and new selection is drawn
   - Check if framebuffer has overlapping/incorrect content

4. **Compare framebuffer vs actual display**
   - Save framebuffer snapshot before refresh
   - Take photo of actual display after refresh
   - Compare - if framebuffer is correct but display is wrong, refresh issue
   - If framebuffer is wrong, drawing issue

5. **Verify framebuffer dirty region tracking**
   - Log all `mark_dirty()` calls
   - Verify dirty regions are correct
   - Check if dirty regions are being consumed correctly

### Expected Findings:
- Framebuffer may have stale content (not cleared properly)
- Framebuffer may have incorrect content (drawing logic issue)
- Framebuffer may be correct but display is wrong (refresh issue)

---

## Agent 3: Partial Refresh Counter Logic Verification

### Strategy: Verify Counter is Actually Triggering Full Refreshes

### Investigation Tasks:

1. **Verify counter increments correctly**
   - Add detailed logging: log counter value before/after each increment
   - Verify counter increments on every `change_selection()` call
   - Check if counter is reset incorrectly

2. **Verify counter threshold check**
   - Log counter value when checking `>= _max_partial_refreshes`
   - Verify check happens at right time
   - Check if condition is ever true (counter may never reach threshold)

3. **Verify full refresh is triggered when counter reaches limit**
   - Add explicit log: "COUNTER REACHED LIMIT - TRIGGERING FULL REFRESH"
   - Verify `self.draw()` is called
   - Verify `service.submit_full(await_completion=True)` is called
   - Check if full refresh actually completes

4. **Verify counter reset logic**
   - Log when counter is reset
   - Verify counter resets after full refresh
   - Check if counter resets incorrectly in `draw()` (line 165)

5. **Test: Log all counter state changes**
   - Log: counter value, when incremented, when reset, when checked
   - Create timeline of counter state
   - Verify counter reaches 8 and triggers full refresh

### Expected Findings:
- Counter may not be incrementing (logic bug)
- Counter may be resetting prematurely (line 165 resets on every `draw()`)
- Counter may reach limit but full refresh not triggered (logic bug)
- Counter threshold may be wrong (8 may be too high)

---

## Agent 4: Refresh Queue and Scheduler Analysis

### Strategy: Verify Refreshes Aren't Being Dropped or Queued Incorrectly

### Investigation Tasks:

1. **Verify partial refreshes are queued correctly**
   - Log every `submit_region()` call with region details
   - Log every `scheduler.submit()` call
   - Verify regions are added to queue

2. **Verify full refresh supersedes partials**
   - When full refresh is submitted, verify queued partials are marked "skipped-by-full"
   - Check if partials are still being processed after full refresh
   - Verify full refresh is processed first

3. **Verify refresh queue doesn't accumulate**
   - Log queue size before/after each operation
   - Check if queue grows unbounded
   - Verify queue is processed in order

4. **Verify refresh completion**
   - Log when each refresh future completes
   - Verify `await_completion=True` actually waits
   - Check if refreshes complete successfully or fail

5. **Test: Force queue flush before full refresh**
   - Call `service.await_all_pending()` before triggering full refresh
   - Verify no partial refreshes are pending
   - Check if this fixes ghosting

### Expected Findings:
- Partial refreshes may be queued after full refresh (ordering issue)
- Full refresh may be dropped (queue issue)
- Refreshes may not complete (future issue)
- Queue may accumulate (processing issue)

---

## Agent 5: Menu Drawing Logic and Artifact Analysis

### Strategy: Verify Menu Drawing Doesn't Leave Artifacts in Framebuffer

### Investigation Tasks:

1. **Verify menu title is drawn correctly**
   - Log title drawing in `MenuRenderer.draw()`
   - Verify title region is marked dirty
   - Check if title is in framebuffer after drawing
   - If title fades, verify it's in framebuffer but not on display

2. **Verify selection clearing logic**
   - In `change_selection()`, verify old selection is fully cleared
   - Check if clearing uses correct fill color (255 = white)
   - Verify cleared region covers entire old selection area
   - Check if arrow is cleared separately (may leave artifact)

3. **Verify region calculations**
   - Log all region calculations in `change_selection()`
   - Verify `combined_region` covers both old and new selections
   - Check if regions are correct (may miss some areas)

4. **Verify atomic drawing**
   - Verify all drawing happens in single `acquire_canvas()` context
   - Check if any drawing happens outside canvas context
   - Verify no interleaved canvas operations

5. **Test: Draw menu to white background**
   - Before drawing menu, explicitly clear entire menu area to white
   - Then draw menu
   - Check if this prevents ghosting (proves clearing is issue)

### Expected Findings:
- Menu title may not be drawn (drawing logic bug)
- Old selection may not be fully cleared (clearing logic bug)
- Regions may not cover all areas (calculation bug)
- Drawing may not be atomic (race condition)

---

## Critical Investigation: Counter Reset Bug

### ALL AGENTS MUST VERIFY:

**Line 165 in menu.py**: `self._partial_refresh_count = 0`

This resets the counter in `draw()`, which is called:
1. On initial menu display (line 532 in doMenu)
2. When counter reaches limit (line 191 in change_selection)

**PROBLEM**: If `draw()` is called for ANY reason, counter resets to 0, even if no full refresh happened!

### Investigation:
- Log every call to `MenuRenderer.draw()`
- Log counter value before/after each `draw()` call
- Verify counter only resets when full refresh actually happens
- Check if counter resets prematurely, preventing full refresh trigger

### Expected Finding:
Counter may reset to 0 on initial menu draw, then never reach 8 again because it keeps resetting.

---

## Investigation Priority

1. **IMMEDIATE**: Verify counter reset bug (line 165)
2. **HIGH**: Verify full refresh is actually sent to hardware (Agent 1, task 1-3)
3. **HIGH**: Verify framebuffer content is correct (Agent 2, task 1-2)
4. **MEDIUM**: Verify counter logic (Agent 3, all tasks)
5. **MEDIUM**: Verify refresh queue (Agent 4, task 1-3)
6. **LOW**: Verify drawing logic (Agent 5, task 1-3)

---

## Implementation Plan

Each agent should:
1. Add specific logging for their investigation tasks
2. Run menu navigation test (navigate 20+ times)
3. Analyze logs to find root cause
4. Report findings with evidence (log excerpts, framebuffer snapshots)
5. Propose fix based on findings (not speculation)

---

## Success Criteria

Root cause is found when:
- Logs show exactly what is wrong (counter, framebuffer, hardware, etc.)
- Evidence proves the issue (not speculation)
- Fix can be implemented based on evidence
- Fix can be verified with same logging

