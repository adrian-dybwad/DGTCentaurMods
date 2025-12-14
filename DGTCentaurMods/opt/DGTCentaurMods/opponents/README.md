# Opponents Module

Opponents are entities that play against the user. They provide moves in response to the game state.

## Architecture

All opponents inherit from the `Opponent` abstract base class, which defines a standard interface:

```python
class Opponent(ABC):
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def get_move(self, board: chess.Board) -> Optional[chess.Move]: ...
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None: ...
    def on_new_game(self) -> None: ...
```

## Built-in Opponents

### EngineOpponent
Plays using a UCI chess engine (Stockfish, Maia, CT800, etc.).

```python
from DGTCentaurMods.opponents import create_engine_opponent

opponent = create_engine_opponent(
    engine_name="stockfish_pi",
    elo_section="1350"
)
opponent.set_move_callback(on_engine_move)
opponent.start()

# Game coordinator tracks player color and calls get_move when it's opponent's turn:
player_color = chess.WHITE
if board.turn != player_color:
    opponent.get_move(board)  # Opponent computes move for board.turn
```

### LichessOpponent
Plays against humans online via Lichess API.

```python
from DGTCentaurMods.opponents import create_lichess_opponent, LichessGameMode

opponent = create_lichess_opponent(
    mode=LichessGameMode.NEW,
    time_minutes=10,
    increment_seconds=5,
    rated=False
)
opponent.set_move_callback(on_lichess_move)
opponent.start()
```

### HumanOpponent
Null opponent for two-player mode where both sides are human.

```python
from DGTCentaurMods.opponents import HumanOpponent

opponent = HumanOpponent()
opponent.start()  # Always succeeds, never generates moves
```

## Creating Custom Opponents

To create a custom opponent, subclass `Opponent` and implement the required methods:

```python
from DGTCentaurMods.opponents import Opponent, OpponentConfig, OpponentState

class MyCustomOpponent(Opponent):
    def start(self) -> bool:
        # Initialize your opponent
        self._set_state(OpponentState.READY)
        return True
    
    def stop(self) -> None:
        # Clean up resources
        self._set_state(OpponentState.STOPPED)
    
    def get_move(self, board: chess.Board) -> Optional[chess.Move]:
        # Compute and return a move, or return None and use callback
        move = self._compute_move(board)
        return move
    
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        # Handle player's move (for stateful opponents)
        pass
    
    def on_new_game(self) -> None:
        # Reset state for new game
        pass
```

## Opponent Lifecycle

1. Create opponent with config
2. Set callbacks (`set_move_callback`, `set_status_callback`)
3. Call `start()` to initialize
4. Track player color in the game coordinator
5. When `board.turn != player_color`, call `get_move(board)`
6. Receive moves via callback or return value
7. Call `on_player_move()` when player moves
8. Call `stop()` to clean up

Note: Opponents don't store which color they play. The caller (game coordinator) tracks the player's color and calls `get_move()` when `board.turn` is not the player's color. The opponent computes a move for whoever's turn it is (`board.turn`).

## Thread Safety

Opponents may run background threads for move computation. The `get_move()` method typically starts a background thread and delivers the move via `_move_callback`. Implementations must ensure thread-safe access to shared state.
