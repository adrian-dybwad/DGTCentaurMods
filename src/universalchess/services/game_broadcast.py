"""
Game state broadcast service using Unix domain sockets.

Provides real-time game state updates from the main application to the web
application. Uses a Unix socket for secure, low-latency IPC.

Architecture:
    Main app (publisher) -> Unix socket -> Web app (subscriber) -> SSE -> Browsers

Message format (JSON):
    {
        "type": "game_state",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "pgn": "1. e4 e5 2. Nf3 ...",
        "turn": "w",
        "move_number": 1,
        "last_move": "e2e4",
        "game_over": false,
        "result": null,
        "white": "Human",
        "black": "Stockfish",
        "timestamp": 1703577600.123
    }

Security:
    - Socket file permissions restrict access to the `pi` user
    - No network exposure (Unix socket only)
    - OS-level authentication via file ownership
"""

import json
import os
import socket
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable, List

try:
    from universalchess.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Socket path - in /run for volatile runtime data
SOCKET_DIR = Path("/run/universalchess")
SOCKET_PATH = SOCKET_DIR / "game.sock"

# Fallback for development (when /run isn't available)
DEV_SOCKET_DIR = Path("/tmp/universalchess")
DEV_SOCKET_PATH = DEV_SOCKET_DIR / "game.sock"


def get_socket_path() -> Path:
    """Get the appropriate socket path based on environment."""
    if SOCKET_DIR.exists() or os.access(SOCKET_DIR.parent, os.W_OK):
        return SOCKET_PATH
    return DEV_SOCKET_PATH


@dataclass
class GameState:
    """Current game state for broadcasting."""
    # NOTE: `fen` is the piece-placement field only (8 ranks with `/`).
    # chessboard.js expects placement-only; full FEN (turn/castling/etc) can crash it.
    fen: str
    # Full FEN (optional). When not provided and `fen` looks like a full FEN,
    # __post_init__ will normalize `fen` to placement-only and store the full value here.
    fen_full: Optional[str] = None
    pgn: str = ""
    turn: str = "w"
    move_number: int = 1
    last_move: Optional[str] = None
    game_over: bool = False
    result: Optional[str] = None
    white: str = "White"
    black: str = "Black"
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

        # Normalize FEN for web display: chessboard.js expects placement-only.
        # If a full FEN is provided in `fen`, split it and preserve the full value.
        if self.fen and " " in self.fen:
            if self.fen_full is None:
                self.fen_full = self.fen
            self.fen = self.fen.split(" ", 1)[0]
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = asdict(self)
        data["type"] = "game_state"
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, json_str: str) -> "GameState":
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        data.pop("type", None)  # Remove type field if present
        return cls(**data)


class GameBroadcaster:
    """
    Publisher side - sends game state updates via Unix socket.
    
    Used by the main application to broadcast moves to the web app.
    """
    
    def __init__(self):
        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._lock = threading.Lock()
    
    def _ensure_socket_dir(self) -> None:
        """Ensure the socket directory exists with correct permissions."""
        socket_path = get_socket_path()
        socket_dir = socket_path.parent
        
        if not socket_dir.exists():
            socket_dir.mkdir(parents=True, mode=0o755)
            log.info(f"[GameBroadcaster] Created socket directory: {socket_dir}")
    
    def connect(self) -> bool:
        """Connect to the game broadcast socket.
        
        Returns:
            True if connected, False otherwise.
        """
        with self._lock:
            if self._connected:
                return True
            
            try:
                self._ensure_socket_dir()
                socket_path = get_socket_path()
                
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                # For DGRAM, we don't connect - we just send to the path
                self._connected = True
                log.info(f"[GameBroadcaster] Ready to broadcast to {socket_path}")
                return True
            except Exception as e:
                log.debug(f"[GameBroadcaster] Failed to initialize: {e}")
                self._connected = False
                return False
    
    def broadcast(self, state: GameState) -> bool:
        """Broadcast game state to subscribers.
        
        Args:
            state: GameState to broadcast.
            
        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._connected:
            if not self.connect():
                return False
        
        try:
            socket_path = get_socket_path()
            message = state.to_json().encode("utf-8")
            self._socket.sendto(message, str(socket_path))
            log.debug(f"[GameBroadcaster] Sent: {state.fen[:20]}...")
            return True
        except FileNotFoundError:
            # Subscriber not listening yet - that's OK
            log.debug("[GameBroadcaster] No subscriber listening")
            return False
        except Exception as e:
            log.debug(f"[GameBroadcaster] Send failed: {e}")
            self._connected = False
            return False
    
    def close(self) -> None:
        """Close the socket."""
        with self._lock:
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            self._connected = False


class GameSubscriber:
    """
    Subscriber side - receives game state updates via Unix socket.
    
    Used by the web application to receive moves from the main app.
    Callbacks are invoked when new game state arrives.
    """
    
    def __init__(self):
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[GameState], None]] = []
        self._lock = threading.Lock()
        self._last_state: Optional[GameState] = None
    
    def _ensure_socket(self) -> None:
        """Create and bind the Unix socket."""
        socket_path = get_socket_path()
        socket_dir = socket_path.parent
        
        # Ensure directory exists
        if not socket_dir.exists():
            socket_dir.mkdir(parents=True, mode=0o755)
        
        # Remove stale socket file
        if socket_path.exists():
            socket_path.unlink()
        
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.bind(str(socket_path))
        self._socket.settimeout(1.0)  # Allow periodic check for shutdown
        
        # Set permissions - only owner can read/write
        os.chmod(socket_path, 0o600)
        
        log.info(f"[GameSubscriber] Listening on {socket_path}")
    
    def add_callback(self, callback: Callable[[GameState], None]) -> None:
        """Register a callback for game state updates.
        
        Args:
            callback: Function to call with GameState on each update.
        """
        with self._lock:
            self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[GameState], None]) -> None:
        """Unregister a callback.
        
        Args:
            callback: Previously registered callback function.
        """
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    def get_last_state(self) -> Optional[GameState]:
        """Get the most recent game state received.
        
        Returns:
            Last GameState or None if no state received yet.
        """
        return self._last_state
    
    def start(self) -> None:
        """Start the subscriber thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        log.info("[GameSubscriber] Started")
    
    def stop(self) -> None:
        """Stop the subscriber thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        # Clean up socket file
        socket_path = get_socket_path()
        if socket_path.exists():
            try:
                socket_path.unlink()
            except Exception:
                pass
        
        log.info("[GameSubscriber] Stopped")
    
    def _receive_loop(self) -> None:
        """Main receive loop - runs in background thread."""
        try:
            self._ensure_socket()
        except Exception as e:
            log.error(f"[GameSubscriber] Failed to create socket: {e}")
            self._running = False
            return
        
        while self._running:
            try:
                data, _ = self._socket.recvfrom(65536)
                message = data.decode("utf-8")
                state = GameState.from_json(message)
                self._last_state = state
                
                # Notify all callbacks
                with self._lock:
                    callbacks = list(self._callbacks)
                
                for callback in callbacks:
                    try:
                        callback(state)
                    except Exception as e:
                        log.error(f"[GameSubscriber] Callback error: {e}")
                
            except socket.timeout:
                # Normal timeout, check if we should continue
                continue
            except Exception as e:
                if self._running:
                    log.error(f"[GameSubscriber] Receive error: {e}")
                    time.sleep(0.1)


# -----------------------------------------------------------------------------
# Singleton instances
# -----------------------------------------------------------------------------

_broadcaster: Optional[GameBroadcaster] = None
_subscriber: Optional[GameSubscriber] = None


def get_broadcaster() -> GameBroadcaster:
    """Get the singleton GameBroadcaster instance."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = GameBroadcaster()
    return _broadcaster


def get_subscriber() -> GameSubscriber:
    """Get the singleton GameSubscriber instance."""
    global _subscriber
    if _subscriber is None:
        _subscriber = GameSubscriber()
    return _subscriber


def broadcast_game_state(
    fen: str,
    pgn: str = "",
    turn: str = "w",
    move_number: int = 1,
    last_move: Optional[str] = None,
    game_over: bool = False,
    result: Optional[str] = None,
    white: str = "White",
    black: str = "Black",
) -> bool:
    """Convenience function to broadcast game state.
    
    Args:
        fen: Current position in FEN notation.
        pgn: Current game PGN string.
        turn: Whose turn ('w' or 'b').
        move_number: Current move number.
        last_move: Last move in UCI notation.
        game_over: Whether the game has ended.
        result: Game result if over ('1-0', '0-1', '1/2-1/2').
        white: White player name.
        black: Black player name.
        
    Returns:
        True if broadcast succeeded, False otherwise.
    """
    state = GameState(
        fen=fen,
        pgn=pgn,
        turn=turn,
        move_number=move_number,
        last_move=last_move,
        game_over=game_over,
        result=result,
        white=white,
        black=black,
    )
    return get_broadcaster().broadcast(state)

