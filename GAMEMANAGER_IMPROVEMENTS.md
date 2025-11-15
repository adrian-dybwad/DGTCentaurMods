# GameManager.py Improvements Analysis

## Major Issues

### 1. **Excessive Global State (20+ globals)**
**Problem**: The file uses 20+ global variables making state management difficult and error-prone.

**Impact**: 
- Hard to track state changes
- Difficult to test
- Risk of state corruption
- No encapsulation

**Solution**: Refactor into a `GameManager` class to encapsulate state.

---

### 2. **Code Duplication**

#### A. Promotion Handling (Lines 536-555)
**Duplicated Code**: Nearly identical promotion logic for white and black pawns:
```python
# Lines 536-545: White pawn promotion
if (field // 8) == 7 and pname == "P":
    screenback = epaper.epaperbuffer.copy()
    board.beep(board.SOUND_GENERAL)
    if forcemove == 0:
        showingpromotion = True
        epaper.promotionOptions(13)
        pr = waitForPromotionChoice()
        epaper.epaperbuffer = screenback.copy()
        showingpromotion = False

# Lines 546-555: Black pawn promotion (nearly identical)
if (field // 8) == 0 and pname == "p":
    screenback = epaper.epaperbuffer.copy()
    board.beep(board.SOUND_GENERAL)
    if forcemove == 0:
        showingpromotion = True
        epaper.promotionOptions(13)
        pr = waitForPromotionChoice()
        showingpromotion = False
        epaper.epaperbuffer = screenback.copy()
```

**Fix**: Extract to `_handle_promotion(field, pname, forcemove)` function.

#### B. Turn Switching Logic (Lines 136-139, 585-592)
**Duplicated Code**: Turn switching appears in multiple places:
```python
# Line 136-139: In checkLastBoardState
if curturn == 0:
    curturn = 1
else:
    curturn = 0

# Lines 585-592: In fieldcallback
if curturn == 0:
    curturn = 1
    if eventcallbackfunction != None:
        eventcallbackfunction(EVENT_WHITE_TURN)
else:
    curturn = 0
    if eventcallbackfunction != None:
        eventcallbackfunction(EVENT_BLACK_TURN)
```

**Fix**: Extract to `_switch_turn()` and `_switch_turn_with_event()` functions.

#### C. Database Result Update Pattern (Lines 597-603, 614-620, 637-643)
**Duplicated Code**: Same pattern repeated 3 times:
```python
tg = session.query(models.Game).filter(models.Game.id == gamedbid).first()
if tg is not None:
    tg.result = resultstr
    session.flush()
    session.commit()
else:
    log.warning(f"[gamemanager.XXX] Game with id {gamedbid} not found in database, cannot update result")
```

**Fix**: Extract to `_update_game_result(resultstr, context)` function.

#### D. Time Formatting (Lines 751-756, 771-775)
**Duplicated Code**: Time formatting logic duplicated:
```python
# In clockThread
wmin = whitetime // 60
wsec = whitetime % 60
bmin = blacktime // 60
bsec = blacktime % 60
timestr = "{:02d}".format(wmin) + ":" + "{:02d}".format(wsec) + "       " + "{:02d}".format(bmin) + ":" + "{:02d}".format(bsec)

# In startClock (nearly identical)
wmin = whitetime // 60
wsec = whitetime % 60
bmin = blacktime // 60
bsec = blacktime % 60
timestr = "{:02d}".format(wmin) + ":" + "{:02d}".format(wsec) + "       " + "{:02d}".format(bmin) + ":" + "{:02d}".format(bsec)
```

**Fix**: Extract to `_format_time(white_seconds, black_seconds)` function.

#### E. UCI Move Parsing (Lines 210-211, 793-794)
**Duplicated Code**: UCI string to square index conversion:
```python
# Line 210-211: In exit_correction_mode
fromnum = ((ord(computermove[1:2]) - ord("1")) * 8) + (ord(computermove[0:1]) - ord("a"))
tonum = ((ord(computermove[3:4]) - ord("1")) * 8) + (ord(computermove[2:3]) - ord("a"))

# Line 793-794: In computerMove
fromnum = ((ord(mv[1:2]) - ord("1")) * 8) + (ord(mv[0:1]) - ord("a"))
tonum = ((ord(mv[3:4]) - ord("1")) * 8) + (ord(mv[2:3]) - ord("a"))
```

**Fix**: Extract to `_uci_to_squares(uci_move)` function returning (from_square, to_square).

---

### 3. **Overly Complex Functions**

#### A. `fieldcallback` (Lines 392-604, 213 lines)
**Problem**: Single function handles:
- Event type detection (lift/place)
- Piece validation
- Legal move calculation
- Forced move handling
- Stale event filtering
- Illegal move detection
- Move execution
- Promotion handling
- Database updates
- Turn switching
- Game outcome checking

**Fix**: Break into smaller functions:
- `_handle_lift_event(field, vpiece)`
- `_handle_place_event(field, vpiece)`
- `_calculate_legal_squares(field)`
- `_execute_move(from_sq, to_sq, promotion)`
- `_check_game_outcome()`

#### B. `keycallback` (Lines 366-390)
**Problem**: Multiple nested if statements checking `inmenu` state.

**Fix**: Use early returns or state machine pattern.

---

### 4. **Magic Numbers and Constants**

**Issues**:
- `startstate` hardcoded bytearray (line 55) - should be computed from chess.Board()
- `64` used multiple times - should be `BOARD_SIZE = 64`
- `8` used for row calculation - should be `BOARD_WIDTH = 8`
- `7` and `0` for promotion rows - should be `PROMOTION_ROW_WHITE = 7`, `PROMOTION_ROW_BLACK = 0`
- `60` for time conversion - should be `SECONDS_PER_MINUTE = 60`
- `2` for clock decrement - should be `CLOCK_DECREMENT_SECONDS = 2`

---

### 5. **Unused Variables**

- `lifted` (line 436) - assigned but never used
- `correction_iteration` (lines 84, 184) - set but never used
- `original_fieldcallback` (lines 85, 331) - assigned but never used

---

### 6. **Inconsistent Patterns**

#### A. Error Handling
- Some functions use try/except (lines 663-668, 731-735)
- Others don't handle errors at all
- Inconsistent error logging

#### B. State Validation
- Some functions validate state (lines 167-173)
- Others assume valid state
- Inconsistent None checks

#### C. Logging
- Some functions log extensively
- Others have minimal logging
- Inconsistent log levels

---

### 7. **Code Quality Issues**

#### A. Commented Code
- Lines 395-397: Commented out code should be removed
- Lines 423-424: Commented code
- Lines 690-693: Commented debug code
- Lines 846-847: Commented code
- Line 854-855: Commented TODO

#### B. Inconsistent Naming
- `cboard` vs `board` (confusing with imported `board` module)
- `vpiece` (unclear name)
- `pc` (unclear abbreviation)
- `pr` (unclear abbreviation)
- `outc` (unclear abbreviation)
- `tg` (unclear abbreviation)

#### C. Type Hints Missing
- No type hints on function parameters or return values
- Makes code harder to understand and maintain

---

### 8. **Logic Improvements**

#### A. Stale Event Filtering (Lines 479-508)
**Problem**: Complex nested conditions for filtering stale events.

**Fix**: Extract to `_is_stale_place_event(field, piece_event, sourcesq, othersourcesq)` function.

#### B. Legal Squares Calculation (Lines 434-452)
**Problem**: Inefficient nested loops checking all 64 squares.

**Fix**: Use `cboard.legal_moves` more efficiently:
```python
legalsquares = [move.to_square for move in cboard.legal_moves if move.from_square == field]
```

#### C. Turn Validation (Lines 427-431)
**Problem**: Verbose conditional logic.

**Fix**: Simplify:
```python
vpiece = (curturn == 0 and pc == False) or (curturn == 1 and pc == True)
# Or better:
vpiece = (curturn == 0) == (pc == False)  # True if piece color matches turn
```

---

### 9. **Database Operations**

#### A. Repeated Session Queries
- Multiple places query `models.Game` by `gamedbid`
- Could cache game object or use a helper

#### B. Transaction Management
- Some operations commit immediately
- Others use flush then commit
- Inconsistent pattern

---

### 10. **Constants Organization**

**Current**: Constants scattered (lines 48-52, 55)

**Better**: Group related constants:
```python
# Event types
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0

# Clock constants
SECONDS_PER_MINUTE = 60
CLOCK_DECREMENT_SECONDS = 2
CLOCK_DISPLAY_LINE = 13

# Move constants
INVALID_SQUARE = -1
```

---

## Recommended Refactoring Priority

### High Priority (Critical)
1. Extract promotion handling to reduce duplication
2. Extract turn switching logic
3. Extract database result update pattern
4. Break down `fieldcallback` into smaller functions
5. Extract UCI move parsing

### Medium Priority (Important)
6. Extract time formatting
7. Simplify stale event filtering logic
8. Improve legal squares calculation
9. Remove unused variables
10. Add constants for magic numbers

### Low Priority (Nice to Have)
11. Refactor to class-based design
12. Add type hints
13. Improve error handling consistency
14. Remove commented code
15. Improve variable naming

---

## Estimated Impact

- **Lines of code reduction**: ~100-150 lines through deduplication
- **Cyclomatic complexity**: Reduce `fieldcallback` from ~25 to ~5-8 per function
- **Maintainability**: Significantly improved through smaller, focused functions
- **Testability**: Much easier to test individual functions
- **Readability**: Clearer intent with better function names

