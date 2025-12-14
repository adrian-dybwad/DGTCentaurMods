"""
Display manager for game-related UI widgets.

This module provides a centralized manager for all game display widgets,
handling widget lifecycle, menu presentation, and display state management.
It separates UI concerns from game logic (GameManager) and protocol handling (ProtocolManager).

Note: This is distinct from the lower-level epaper Manager class which handles
framebuffer rendering. This DisplayManager orchestrates game-specific widgets.

Responsibilities:
- Create and manage ChessBoardWidget, GameAnalysisWidget
- Handle promotion menu display and selection
- Handle back button menu (resign/draw/cancel)
- Restore display after menu interactions
- React to game events (new game, moves, etc.)
"""

import threading
import pathlib
import chess
import chess.engine

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies
_board_module = None
_widgets_loaded = False
_ChessBoardWidget = None
_GameAnalysisWidget = None
_ChessClockWidget = None
_IconMenuWidget = None
_IconMenuEntry = None
_SplashScreen = None
_BrainHintWidget = None
_GameOverWidget = None
_AlertWidget = None


def _get_board():
    """Lazily import and return the board module."""
    global _board_module
    if _board_module is None:
        from DGTCentaurMods.board import board
        _board_module = board
    return _board_module


def _load_widgets():
    """Lazily load widget classes."""
    global _widgets_loaded, _ChessBoardWidget, _GameAnalysisWidget, _ChessClockWidget
    global _IconMenuWidget, _IconMenuEntry, _SplashScreen, _BrainHintWidget
    global _GameOverWidget, _AlertWidget
    
    if _widgets_loaded:
        return
    
    from DGTCentaurMods.epaper import (
        ChessBoardWidget, GameAnalysisWidget, ChessClockWidget,
        IconMenuWidget, IconMenuEntry, SplashScreen, BrainHintWidget,
        AlertWidget
    )
    from DGTCentaurMods.epaper.game_over import GameOverWidget
    _ChessBoardWidget = ChessBoardWidget
    _GameAnalysisWidget = GameAnalysisWidget
    _ChessClockWidget = ChessClockWidget
    _IconMenuWidget = IconMenuWidget
    _IconMenuEntry = IconMenuEntry
    _SplashScreen = SplashScreen
    _BrainHintWidget = BrainHintWidget
    _GameOverWidget = GameOverWidget
    _AlertWidget = AlertWidget
    _widgets_loaded = True


# Starting position FEN
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class DisplayManager:
    """Manager for game display widgets.
    
    Manages the lifecycle of game-related widgets and handles UI interactions
    like menus. Provides a clean interface for game logic to update the display
    without knowing about widget implementation details.
    
    Note: This is distinct from the lower-level epaper Manager class. This
    DisplayManager orchestrates game-specific widgets at a higher level.
    
    Layout (below status bar at y=16):
    - Chess board: y=16, height=128 (16 pixels per square * 8)
    - Clock widget: y=144, height=72 (turn indicator / time - prominent display)
    - Analysis widget: y=216, height=80 (eval bar and history graph)
    
    Attributes:
        chess_board_widget: The chess board display widget
        clock_widget: The chess clock / turn indicator widget
        analysis_widget: The game analysis/evaluation widget
        analysis_engine: UCI engine for position analysis
    """
    
    def __init__(self, flip_board: bool = False, show_analysis: bool = True,
                 analysis_engine_path: str = None, on_exit: callable = None,
                 hand_brain_mode: bool = False, initial_fen: str = None,
                 time_control: int = 0, show_board: bool = True,
                 show_clock: bool = True,
                 show_graph: bool = True, analysis_mode: bool = True):
        """Initialize the display controller.
        
        Args:
            flip_board: If True, display board from black's perspective
            show_analysis: If True, show analysis widget (default visible)
            analysis_engine_path: Path to UCI engine for analysis (e.g., ct800)
            on_exit: Callback function() when user requests exit via back menu
            hand_brain_mode: If True, show brain hint widget for Hand+Brain variant
            initial_fen: FEN string for initial position. If None, uses starting position.
            time_control: Time per player in minutes (0 = disabled/untimed, shows turn only)
            show_board: If True, show the chess board widget
            show_clock: If True, show the clock/turn indicator widget
            show_graph: If True, show the history graph in analysis widget
            analysis_mode: If True, create analysis engine/widget (may be hidden by show_analysis)
        """
        _load_widgets()
        
        self._flip_board = flip_board
        self._show_analysis = show_analysis
        self._analysis_mode = analysis_mode  # Whether to create analysis engine/widget at all
        self._on_exit = on_exit
        self._hand_brain_mode = hand_brain_mode
        self._initial_fen = initial_fen or STARTING_FEN
        self._time_control = time_control  # Minutes per player (0 = disabled)
        self._show_board = show_board
        self._show_clock = show_clock
        self._show_graph = show_graph
        
        # Widgets
        self.chess_board_widget = None
        self.clock_widget = None
        self.analysis_widget = None
        self.analysis_engine = None
        self.brain_hint_widget = None
        self.alert_widget = None
        self.pause_widget = None
        
        # Pause state
        self._is_paused = False
        self._paused_active_color = None  # Which clock was running before pause
        
        # Menu state
        self._menu_active = False
        self._current_menu = None
        self._menu_result_callback = None
        
        # Key callback for routing during menu
        self._original_key_callback = None
        self._key_callback = None
        
        # Store engine path for async initialization
        self._analysis_engine_path = analysis_engine_path
        self._engine_init_thread = None
        
        # Initialize widgets first (fast, non-blocking)
        self._init_widgets()
        
        # Initialize analysis engine asynchronously (slow, done in background)
        if analysis_engine_path:
            self._init_analysis_engine_async(analysis_engine_path)
    
    def _init_analysis_engine_async(self, engine_path: str):
        """Initialize the UCI analysis engine asynchronously.
        
        Starts engine initialization in a background thread to avoid blocking
        game startup. The analysis widget will work without an engine until
        initialization completes.
        
        Args:
            engine_path: Path to the UCI engine executable
        """
        def _init_engine():
            try:
                resolved_path = str(pathlib.Path(engine_path).resolve())
                log.info(f"[DisplayManager] Starting analysis engine initialization: {resolved_path}")
                engine = chess.engine.SimpleEngine.popen_uci(resolved_path, timeout=None)
                
                # Set the engine on both DisplayManager and the analysis widget
                # The worker thread is already running and will start processing
                # queued positions once the engine is set
                self.analysis_engine = engine
                if self.analysis_widget:
                    self.analysis_widget.set_analysis_engine(engine)
                
                log.info(f"[DisplayManager] Analysis engine ready: {resolved_path}")
            except Exception as e:
                log.warning(f"[DisplayManager] Could not initialize analysis engine: {e}")
                self.analysis_engine = None
        
        self._engine_init_thread = threading.Thread(
            target=_init_engine,
            name="analysis-engine-init",
            daemon=True
        )
        self._engine_init_thread.start()
    
    def _reload_display_settings(self):
        """Reload display settings from config file.
        
        Called when display menu changes settings during a game.
        """
        from DGTCentaurMods.board.settings import Settings
        
        def load_bool(key: str, default: bool) -> bool:
            val = Settings.read('game', key, 'true' if default else 'false')
            return val.lower() == 'true'
        
        self._show_board = load_bool('show_board', True)
        self._show_clock = load_bool('show_clock', True)
        self._show_analysis = load_bool('show_analysis', True)
        self._show_graph = load_bool('show_graph', True)
        
        log.info(f"[DisplayManager] Reloaded display settings: board={self._show_board}, "
                 f"clock={self._show_clock}, analysis={self._show_analysis}, "
                 f"graph={self._show_graph}")
    
    def _init_widgets(self):
        """Create and add widgets to the display manager.
        
        Layout:
        - Status bar: y=0, height=16
        - Chess board: y=16, height=128
        - Clock widget: y=144, height=72 (prominent turn/time display)
        - Analysis widget: y=216, height=80 (eval bar and history)
        
        Widget creation rules:
        - Clock widget: Always created if time_control > 0, hidden if show_clock=False
        - Analysis widget: Always created if analysis mode enabled, hidden if show_analysis=False
        - Board widget: Always created, hidden if show_board=False
        """
        # Reload settings from config in case they changed (e.g., via display menu)
        self._reload_display_settings()
        
        board = _get_board()
        
        if not board.display_manager:
            log.error("[DisplayManager] No epaper manager available")
            return
        
        # Clear any existing widgets
        board.display_manager.clear_widgets()

        # Create chess board widget at y=16 (below status bar)
        # Uses cached sprites from preload_sprites() if available
        self.chess_board_widget = _ChessBoardWidget(0, 16, self._initial_fen)
        if self._flip_board:
            self.chess_board_widget.set_flip(True)
        
        # Always add board widget, but hide if show_board=False
        board.display_manager.add_widget(self.chess_board_widget)
        if self._show_board:
            log.info("[DisplayManager] Chess board widget initialized (visible)")
        else:
            self.chess_board_widget.hide()
            log.info("[DisplayManager] Chess board widget initialized (hidden)")
        
        # Calculate dynamic layout based on which widgets are shown
        # Available space: y=144 to y=296 (152 pixels total)
        # Layout depends on what's enabled:
        # - Clock needs more space if timed mode, less if just turn indicator
        # - Analysis uses fixed height when visible
        
        # Determine analysis widget height based on visibility
        if self._show_analysis:
            if self._show_graph:
                # Full analysis: score text + graph
                analysis_height = 80
            else:
                # Score text only (no graph)
                analysis_height = 54
        else:
            analysis_height = 0
        
        # Clock gets remaining space
        clock_height = 152 - analysis_height
        if clock_height < 36:
            clock_height = 36  # Minimum for turn indicator
        
        clock_y = 144
        analysis_y = clock_y + clock_height
        
        log.info(f"[DisplayManager] Layout: clock_height={clock_height}, analysis_height={analysis_height}")
        
        # Create clock widget directly below board
        # Shows times if time_control > 0, otherwise shows turn indicator only
        # flip matches board orientation so clock top matches board top
        timed_mode = self._time_control > 0
        self.clock_widget = _ChessClockWidget(
            x=0, y=clock_y, width=128, height=clock_height,
            timed_mode=timed_mode, flip=self._flip_board
        )
        # Set initial times if timed mode is enabled
        if self._time_control > 0:
            initial_seconds = self._time_control * 60
            self.clock_widget.set_times(initial_seconds, initial_seconds)
        
        # Always add clock widget if timed mode, hidden if show_clock=False
        # For untimed mode, only add if show_clock=True
        if timed_mode:
            board.display_manager.add_widget(self.clock_widget)
            if self._show_clock:
                log.info(f"[DisplayManager] Clock widget initialized (visible, y={clock_y}, height={clock_height}, time_control={self._time_control} min)")
            else:
                self.clock_widget.hide()
                log.info(f"[DisplayManager] Clock widget initialized (hidden, y={clock_y}, height={clock_height}, time_control={self._time_control} min)")
        elif self._show_clock:
            board.display_manager.add_widget(self.clock_widget)
            log.info(f"[DisplayManager] Clock widget initialized (visible, turn indicator only, y={clock_y}, height={clock_height})")
        else:
            log.info("[DisplayManager] Clock widget disabled (untimed mode)")
        
        # Create analysis widget below clock - only if analysis_mode is enabled
        # The widget is created but may be hidden based on show_analysis setting
        if self._analysis_mode:
            bottom_color = "black" if self.chess_board_widget.flip else "white"
            self.analysis_widget = _GameAnalysisWidget(
                x=0, y=analysis_y, width=128, height=analysis_height if analysis_height > 0 else 80,
                bottom_color=bottom_color,
                analysis_engine=self.analysis_engine,
                show_graph=self._show_graph
            )
            
            if not self._show_analysis:
                self.analysis_widget.hide()
            
            board.display_manager.add_widget(self.analysis_widget)
            log.info(f"[DisplayManager] Analysis widget initialized (visible={self._show_analysis}, graph={self._show_graph})")
        else:
            self.analysis_widget = None
            log.info("[DisplayManager] Analysis mode disabled - no analysis widget created")
        
        # Create alert widget for CHECK/QUEEN warnings (y=144, overlays clock widget)
        # Alert widget is hidden by default and shown when check or queen threat occurs
        self.alert_widget = _AlertWidget(0, 144, 128, 40)
        board.display_manager.add_widget(self.alert_widget)
        log.info("[DisplayManager] Alert widget initialized (hidden)")
        
        # Create brain hint widget for Hand+Brain mode (y=144, replaces clock)
        if self._hand_brain_mode:
            self.brain_hint_widget = _BrainHintWidget(0, 144, 128, 72)
            # Hide clock widget in hand+brain mode, brain hint takes its place
            if self.clock_widget:
                self.clock_widget.hide()
            board.display_manager.add_widget(self.brain_hint_widget)
            log.info("[DisplayManager] Brain hint widget initialized")
    
    def set_key_callback(self, callback: callable):
        """Set the key callback for routing keys during normal play.
        
        Args:
            callback: Function(key) to call for key events
        """
        self._key_callback = callback
    
    def update_position(self, fen: str):
        """Update the chess board display with a new position.
        
        Args:
            fen: FEN string of the new position
        """
        if self.chess_board_widget:
            try:
                self.chess_board_widget.set_fen(fen)
            except Exception as e:
                log.error(f"[DisplayManager] Error updating position: {e}")
    
    def analyze_position(self, board_obj: chess.Board,
                        is_first_move: bool = False, time_limit: float = 0.3):
        """Trigger position analysis.
        
        Analysis runs even when widget is hidden to collect history.
        
        Args:
            board_obj: chess.Board object to analyze
            is_first_move: If True, don't add to history
            time_limit: Analysis time limit in seconds
        """
        if self.analysis_widget:
            try:
                self.analysis_widget.analyze_position(
                    board_obj, is_first_move, time_limit
                )
            except Exception as e:
                log.debug(f"[DisplayManager] Error analyzing position: {e}")
    
    def get_hint_move(self, board_obj, time_limit: float = 1.0):
        """Get a hint move for the current position.
        
        Uses the analysis engine to find the best move.
        
        Args:
            board_obj: chess.Board object to analyze
            time_limit: Analysis time limit in seconds (default 1.0 for hints)
            
        Returns:
            chess.Move object if a hint is available, None otherwise
        """
        if not self.analysis_engine:
            log.warning("[DisplayManager] No analysis engine available for hint")
            return None
        
        try:
            import chess.engine
            result = self.analysis_engine.play(board_obj, chess.engine.Limit(time=time_limit))
            if result.move:
                log.info(f"[DisplayManager] Hint move: {result.move.uci()}")
                return result.move
        except Exception as e:
            log.warning(f"[DisplayManager] Error getting hint move: {e}")
        
        return None
    
    def show_hint(self, move) -> None:
        """Show a hint move on the display and LEDs.
        
        Args:
            move: chess.Move object to show as hint
        """
        if not move:
            return
        
        if self.alert_widget:
            # Format move as readable text
            move_text = move.uci()
            from_sq = move.from_square
            to_sq = move.to_square
            
            self.alert_widget.show_hint(move_text, from_sq, to_sq)
            log.info(f"[DisplayManager] Showing hint: {move_text}")
    
    def toggle_analysis(self):
        """Toggle analysis widget visibility."""
        if self.analysis_widget:
            if self.analysis_widget.visible:
                log.info("[DisplayManager] Hiding analysis widget")
                self.analysis_widget.hide()
            else:
                log.info("[DisplayManager] Showing analysis widget")
                self.analysis_widget.show()
    
    def reset_analysis(self):
        """Reset analysis widget (clear history, reset score)."""
        if self.analysis_widget:
            try:
                log.info("[DisplayManager] Resetting analysis widget")
                self.analysis_widget.reset()
            except Exception as e:
                log.warning(f"[DisplayManager] Error resetting analysis: {e}")
        # Also clear brain hint on reset
        if self.brain_hint_widget:
            self.brain_hint_widget.clear()
    
    def remove_last_analysis_score(self):
        """Remove the last score from analysis history.
        
        Called on takeback to keep analysis history in sync with game state.
        """
        if self.analysis_widget:
            try:
                self.analysis_widget.remove_last_score()
                log.debug("[DisplayManager] Removed last analysis score (takeback)")
            except Exception as e:
                log.warning(f"[DisplayManager] Error removing last analysis score: {e}")
    
    def set_clock_times(self, white_seconds: int, black_seconds: int) -> None:
        """Set the chess clock times for both players.
        
        Args:
            white_seconds: White's time in seconds
            black_seconds: Black's time in seconds
        """
        if self.clock_widget:
            self.clock_widget.set_times(white_seconds, black_seconds)
    
    def set_clock_active(self, color: str) -> None:
        """Set which player's clock is active (whose turn it is).
        
        Args:
            color: 'white', 'black', or None (paused)
        """
        if self.clock_widget:
            self.clock_widget.set_active(color)
    
    def start_clock(self, active_color: str = 'white') -> None:
        """Start the chess clock.
        
        Args:
            active_color: Which player's clock starts running
        """
        if self.clock_widget and self._time_control > 0:
            self.clock_widget.start(active_color)
    
    def switch_clock_turn(self) -> None:
        """Switch which player's clock is running."""
        if self.clock_widget:
            self.clock_widget.switch_turn()
    
    def pause_clock(self) -> None:
        """Pause the chess clock."""
        if self.clock_widget:
            self.clock_widget.pause()
    
    def stop_clock(self) -> None:
        """Stop the chess clock completely."""
        if self.clock_widget:
            self.clock_widget.stop()
    
    def reset_clock(self) -> None:
        """Reset the chess clock to initial time and stop it.
        
        Called when a new game starts to reset clock state.
        The clock will not start until the first move is made.
        """
        if self.clock_widget and self._time_control > 0:
            # Stop the clock first
            self.clock_widget.stop()
            # Reset to initial time
            initial_seconds = self._time_control * 60
            self.clock_widget.set_times(initial_seconds, initial_seconds)
            log.info(f"[DisplayManager] Clock reset to {self._time_control} min per player")
    
    def toggle_pause(self) -> bool:
        """Toggle pause state for the game.
        
        When paused:
        - Clock is paused
        - LEDs are turned off
        - A pause widget is shown in the center of the screen
        
        When resumed:
        - Clock resumes for the previously active player
        - Pause widget is hidden
        
        Returns:
            True if now paused, False if now resumed
        """
        if self._is_paused:
            self._resume_game()
            return False
        else:
            self._pause_game()
            return True
    
    def _pause_game(self) -> None:
        """Pause the game - stop clock, turn off LEDs, show pause widget."""
        if self._is_paused:
            return
        
        self._is_paused = True
        board = _get_board()
        
        # Remember which clock was active so we can resume it
        if self.clock_widget:
            self._paused_active_color = self.clock_widget._active_color
            self.clock_widget.pause()
        
        # Turn off LEDs
        board.ledsOff()
        
        # Show pause widget (centered on screen)
        # Import here to avoid circular imports
        from DGTCentaurMods.epaper.text import TextWidget, Justify
        from DGTCentaurMods.epaper.framework.widget import Widget
        from PIL import Image, ImageDraw
        
        # Create a custom pause widget with icon and text
        class PauseWidget(Widget):
            """Widget showing pause icon and PAUSED text."""
            def __init__(self):
                # Centered on 128x296 display
                super().__init__(x=0, y=98, width=128, height=100)
                self._text_widget = TextWidget(
                    x=0, y=60, width=128, height=30,
                    text="PAUSED", font_size=24,
                    justify=Justify.CENTER, transparent=True
                )
            
            def render(self) -> Image.Image:
                img = Image.new("1", (self.width, self.height), 255)
                draw = ImageDraw.Draw(img)
                
                # Draw pause icon (two vertical bars) centered at top
                bar_width = 12
                bar_height = 50
                gap = 16
                total_width = bar_width * 2 + gap
                start_x = (self.width - total_width) // 2
                start_y = 5
                
                # Left bar
                draw.rectangle([start_x, start_y, start_x + bar_width, start_y + bar_height], fill=0)
                # Right bar
                draw.rectangle([start_x + bar_width + gap, start_y, 
                               start_x + bar_width * 2 + gap, start_y + bar_height], fill=0)
                
                # Draw "PAUSED" text below
                self._text_widget.draw_on(img, 0, 60, text_color=0)
                
                return img
        
        self.pause_widget = PauseWidget()
        board.display_manager.add_widget(self.pause_widget)
        
        log.info("[DisplayManager] Game paused")
    
    def _resume_game(self) -> None:
        """Resume the game - restart clock, remove pause widget."""
        if not self._is_paused:
            return
        
        self._is_paused = False
        board = _get_board()
        
        # Remove pause widget
        if self.pause_widget:
            board.display_manager.remove_widget(self.pause_widget)
            self.pause_widget = None
        
        # Resume clock with previously active color
        if self.clock_widget and self._paused_active_color:
            self.clock_widget.start(self._paused_active_color)
            log.info(f"[DisplayManager] Clock resumed for {self._paused_active_color}")
        
        self._paused_active_color = None
        log.info("[DisplayManager] Game resumed")
    
    def is_paused(self) -> bool:
        """Check if the game is currently paused.
        
        Returns:
            True if game is paused, False otherwise
        """
        return self._is_paused
    
    def clear_pause(self) -> None:
        """Clear pause state without resuming clock.
        
        Called on new game to ensure clean state.
        """
        if self._is_paused:
            board = _get_board()
            # Remove pause widget if present
            if self.pause_widget:
                board.display_manager.remove_widget(self.pause_widget)
                self.pause_widget = None
            self._is_paused = False
            self._paused_active_color = None
            log.info("[DisplayManager] Pause state cleared")
    
    def get_clock_times(self) -> tuple:
        """Get the current clock times for both players.

        Returns:
            Tuple of (white_seconds, black_seconds), or (None, None) if no clock
        """
        if self.clock_widget:
            return self.clock_widget.get_final_times()
        return (None, None)

    def get_eval_score(self) -> int:
        """Get the current evaluation score in centipawns.

        Returns:
            Evaluation score in centipawns (from white's perspective), or None if unavailable.
            Score is multiplied by 100 to convert from pawns to centipawns.
        """
        if self.analysis_widget:
            # score_value is in pawns (-12 to +12), convert to centipawns
            return int(self.analysis_widget.score_value * 100)
        return None

    def set_score_history(self, centipawn_scores: list) -> None:
        """Set the score history from database values (for restoring on resume).

        Args:
            centipawn_scores: List of scores in centipawns (integers).
                             Will be converted to pawns for the widget.
        """
        if self.analysis_widget and centipawn_scores:
            # Convert centipawns to pawns (-12 to +12 clamped)
            pawn_scores = []
            for cp in centipawn_scores:
                if cp is not None:
                    pawn_score = cp / 100.0
                    # Clamp to display range
                    pawn_score = max(-12, min(12, pawn_score))
                    pawn_scores.append(pawn_score)
            if pawn_scores:
                self.analysis_widget.set_score_history(pawn_scores)
                log.info(f"[DisplayManager] Restored {len(pawn_scores)} scores to analysis widget")

    def set_on_flag(self, callback) -> None:
        """Set callback for when a player's time expires (flag).
        
        Args:
            callback: Function(color: str) where color is 'white' or 'black'
        """
        if self.clock_widget:
            self.clock_widget.on_flag = callback
    
    def set_brain_hint(self, piece_symbol: str) -> None:
        """Set the brain hint piece type for Hand+Brain mode.
        
        Args:
            piece_symbol: Piece symbol (K, Q, R, B, N, P) or empty to clear
        """
        if self.brain_hint_widget:
            self.brain_hint_widget.set_piece(piece_symbol)
    
    def clear_brain_hint(self) -> None:
        """Clear the brain hint display."""
        if self.brain_hint_widget:
            self.brain_hint_widget.clear()
    
    def show_check_alert(self, is_black_in_check: bool, attacker_square: int, king_square: int) -> None:
        """Show CHECK alert and flash LEDs from attacker to king.
        
        Args:
            is_black_in_check: True if black king is in check, False if white
            attacker_square: Square index (0-63) of the piece giving check
            king_square: Square index (0-63) of the king in check
        """
        if self.alert_widget:
            self.alert_widget.show_check(is_black_in_check, attacker_square, king_square)
    
    def show_queen_threat(self, is_black_queen_threatened: bool, 
                          attacker_square: int, queen_square: int) -> None:
        """Show YOUR QUEEN alert and flash LEDs from attacker to queen.
        
        Part of DisplayBridge interface.
        
        Args:
            is_black_queen_threatened: True if black queen is threatened, False if white
            attacker_square: Square index (0-63) of the attacking piece
            queen_square: Square index (0-63) of the threatened queen
        """
        if self.alert_widget:
            self.alert_widget.show_queen_threat(is_black_queen_threatened, attacker_square, queen_square)
    
    def clear_alerts(self) -> None:
        """Clear any active alerts from the display.
        
        Part of DisplayBridge interface.
        """
        if self.alert_widget:
            self.alert_widget.hide()
    
    def hide_alert(self) -> None:
        """Hide the alert widget. Alias for clear_alerts."""
        self.clear_alerts()
    
    def show_promotion_menu(self, is_white: bool) -> str:
        """Show promotion piece selection menu.
        
        Blocks until user selects a piece or timeout.
        
        Args:
            is_white: True if white pawn is promoting
            
        Returns:
            Promotion piece letter ('q', 'r', 'b', 'n')
        """
        board = _get_board()
        
        # Create menu entries with chess piece icons
        color_suffix = "w" if is_white else "b"
        
        entries = [
            _IconMenuEntry(key="q", label="Queen", icon_name=f"Q{color_suffix}"),
            _IconMenuEntry(key="r", label="Rook", icon_name=f"R{color_suffix}"),
            _IconMenuEntry(key="b", label="Bishop", icon_name=f"B{color_suffix}"),
            _IconMenuEntry(key="n", label="Knight", icon_name=f"N{color_suffix}"),
        ]
        
        # Selection synchronization
        selection_event = threading.Event()
        selected_piece = ["q"]  # Default to queen
        
        def on_select(entry_key: str):
            selected_piece[0] = entry_key
            selection_event.set()
        
        # Create and display menu
        promotion_menu = _IconMenuWidget(
            x=0, y=0, width=128, height=296,
            entries=entries,
            on_select=on_select
        )
        promotion_menu.activate()
        self._menu_active = True
        self._current_menu = promotion_menu
        
        # Clear display and show menu
        if board.display_manager:
            board.display_manager.clear_widgets(addStatusBar=False)
            future = board.display_manager.add_widget(promotion_menu)
            if future:
                try:
                    future.result(timeout=2.0)
                except Exception:
                    pass
        
        # Route keys to menu
        self._original_key_callback = self._key_callback
        self._key_callback = lambda key: promotion_menu.handle_key(key)
        
        # Wait for selection
        selection_event.wait(timeout=60.0)
        
        # Restore key callback
        self._key_callback = self._original_key_callback
        
        # Cleanup
        promotion_menu.deactivate()
        self._menu_active = False
        self._current_menu = None
        
        # Restore game display
        self._restore_game_display()
        
        log.info(f"[DisplayManager] Promotion selected: {selected_piece[0]}")
        return selected_piece[0]
    
    def show_back_menu(self, on_result: callable, is_two_player: bool = False):
        """Show the back button menu (resign/draw/cancel).
        
        Non-blocking - calls on_result when user makes a selection.
        
        Args:
            on_result: Callback function(result: str) with result:
                      'resign', 'resign_white', 'resign_black', 'draw', 'cancel', or 'exit'
            is_two_player: If True, show separate resign options for white and black
        """
        board = _get_board()
        
        log.info(f"[DisplayManager] Showing back menu (two_player={is_two_player})")
        
        if is_two_player:
            # In 2-player mode, show separate resign options for each side
            # White flag (white fill, black border) for white resigns
            # Black flag (black fill, white border) for black resigns
            entries = [
                _IconMenuEntry(key="resign_white", label="White\nResigns", icon_name="resign_white"),
                _IconMenuEntry(key="resign_black", label="Black\nResigns", icon_name="resign_black"),
                _IconMenuEntry(key="draw", label="Draw", icon_name="draw"),
                _IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel"),
            ]
        else:
            entries = [
                _IconMenuEntry(key="resign", label="Resign", icon_name="resign"),
                _IconMenuEntry(key="draw", label="Draw", icon_name="draw"),
                _IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel"),
            ]
        
        # Create menu - default to Cancel (last item)
        back_menu = _IconMenuWidget(
            x=0, y=0, width=128, height=296,
            entries=entries,
            selected_index=len(entries) - 1  # Default to Cancel (last item)
        )
        
        self._menu_result_callback = on_result
        self._current_menu = back_menu
        self._menu_active = True
        
        # Clear display and show menu
        if board.display_manager:
            board.display_manager.clear_widgets(addStatusBar=False)
            future = board.display_manager.add_widget(back_menu)
            if future:
                try:
                    future.result(timeout=2.0)
                except Exception as e:
                    log.debug(f"[DisplayManager] Error displaying menu: {e}")
        
        # Activate menu
        back_menu.activate()
        
        # Start thread to wait for result
        def wait_for_result():
            try:
                back_menu._selection_event.wait()
                result = back_menu._selection_result or "BACK"
                
                log.info(f"[DisplayManager] Back menu result: {result}")
                
                # Cleanup
                self._menu_active = False
                back_menu.deactivate()
                self._current_menu = None
                
                # Map special keys
                if result == "BACK":
                    result = "cancel"
                elif result == "SHUTDOWN":
                    result = "exit"
                
                # Restore display for cancel, or let caller handle for resign/draw
                if result == "cancel":
                    self._restore_game_display()
                
                # Call result callback
                if self._menu_result_callback:
                    self._menu_result_callback(result)
                    
            except Exception as e:
                log.error(f"[DisplayManager] Error in back menu: {e}")
                import traceback
                traceback.print_exc()
                self._menu_active = False
                self._current_menu = None
                if self._menu_result_callback:
                    self._menu_result_callback("cancel")
        
        wait_thread = threading.Thread(target=wait_for_result, daemon=True)
        wait_thread.start()
    
    def cancel_menu(self):
        """Cancel the active menu by simulating a BACK key press.
        
        This is called when an external event (like pieces being returned to position)
        should dismiss the menu. It uses the standard BACK key handling path to ensure
        proper cleanup and display restoration.
        """
        if self._menu_active and self._current_menu:
            log.info("[DisplayManager] Cancelling menu via simulated BACK key")
            board = _get_board()
            self._current_menu.handle_key(board.Key.BACK)
    
    def show_king_lift_resign_menu(self, king_color, on_result: callable):
        """Show resign confirmation menu when king is held off board for 3+ seconds.
        
        Non-blocking - calls on_result when user makes a selection.
        
        Args:
            king_color: chess.WHITE or chess.BLACK - the color of the lifted king
            on_result: Callback function(result: str) with result:
                      'resign' or 'cancel'
        """
        board = _get_board()
        
        color_name = "White" if king_color else "Black"
        # Use same resign icons as kings-in-center: resign_white for white, resign_black for black
        icon_name = "resign_white" if king_color else "resign_black"
        log.info(f"[DisplayManager] Showing king-lift resign menu for {color_name}")
        
        entries = [
            _IconMenuEntry(key="resign", label=f"Resign\n{color_name}?", icon_name=icon_name),
            _IconMenuEntry(key="cancel", label="No", icon_name="cancel"),
        ]
        
        # Create menu - default to No (cancel)
        resign_menu = _IconMenuWidget(
            x=0, y=0, width=128, height=296,
            entries=entries,
            selected_index=1  # Default to No (cancel)
        )
        
        self._menu_result_callback = on_result
        self._current_menu = resign_menu
        self._menu_active = True
        
        # Clear display and show menu
        if board.display_manager:
            board.display_manager.clear_widgets(addStatusBar=False)
            future = board.display_manager.add_widget(resign_menu)
            if future:
                try:
                    future.result(timeout=2.0)
                except Exception as e:
                    log.debug(f"[DisplayManager] Error displaying menu: {e}")
        
        # Play a beep to indicate the gesture was recognized
        board.beep(board.SOUND_GENERAL)
        
        # Activate menu
        resign_menu.activate()
        
        # Start thread to wait for result
        def wait_for_result():
            try:
                resign_menu._selection_event.wait()
                result = resign_menu._selection_result or "BACK"
                
                log.info(f"[DisplayManager] King-lift resign menu result: {result}")
                
                # Cleanup
                self._menu_active = False
                resign_menu.deactivate()
                self._current_menu = None
                
                # Map special keys
                if result == "BACK":
                    result = "cancel"
                elif result == "SHUTDOWN":
                    result = "cancel"  # Don't shutdown from this menu
                
                # Restore display for cancel, or let caller handle for resign
                if result == "cancel":
                    self._restore_game_display()
                
                # Call result callback
                if self._menu_result_callback:
                    self._menu_result_callback(result)
                    
            except Exception as e:
                log.error(f"[DisplayManager] Error in king-lift resign menu: {e}")
                import traceback
                traceback.print_exc()
                self._menu_active = False
                self._current_menu = None
                if self._menu_result_callback:
                    self._menu_result_callback("cancel")
        
        wait_thread = threading.Thread(target=wait_for_result, daemon=True)
        wait_thread.start()
    
    def handle_key(self, key):
        """Route key events to active menu or external callback.
        
        Args:
            key: Key that was pressed (board.Key enum)
        """
        if self._menu_active and self._current_menu:
            self._current_menu.handle_key(key)
        elif self._key_callback:
            self._key_callback(key)
    
    def is_menu_active(self) -> bool:
        """Check if a menu is currently being displayed.
        
        Returns:
            True if a menu is active
        """
        return self._menu_active
    
    def _restore_game_display(self):
        """Restore the normal game display widgets after menu."""
        board = _get_board()
        
        try:
            if board.display_manager:
                board.display_manager.clear_widgets(addStatusBar=True)
                
                # Re-add chess board widget
                if self.chess_board_widget:
                    future = board.display_manager.add_widget(self.chess_board_widget)
                    if future:
                        try:
                            future.result(timeout=2.0)
                        except Exception:
                            pass
                
                # Re-add clock widget (or brain hint if in Hand+Brain mode)
                if self._hand_brain_mode and self.brain_hint_widget:
                    future = board.display_manager.add_widget(self.brain_hint_widget)
                    if future:
                        try:
                            future.result(timeout=2.0)
                        except Exception:
                            pass
                elif self.clock_widget:
                    future = board.display_manager.add_widget(self.clock_widget)
                    if future:
                        try:
                            future.result(timeout=2.0)
                        except Exception:
                            pass
                
                # Re-add analysis widget
                if self.analysis_widget:
                    future = board.display_manager.add_widget(self.analysis_widget)
                    if future:
                        try:
                            future.result(timeout=2.0)
                        except Exception:
                            pass
                            
                log.debug("[DisplayManager] Game display restored")
        except Exception as e:
            log.error(f"[DisplayManager] Error restoring display: {e}")
    
    def show_splash(self, message: str):
        """Show a splash screen with a message.
        
        Args:
            message: Message to display
        """
        board = _get_board()
        
        try:
            if board.display_manager:
                board.display_manager.clear_widgets(addStatusBar=False)
                splash = _SplashScreen(message=message)
                future = board.display_manager.add_widget(splash)
                if future:
                    try:
                        future.result(timeout=2.0)
                    except Exception:
                        pass
        except Exception as e:
            log.debug(f"[DisplayManager] Error showing splash: {e}")
    
    def show_game_over(self, result: str, termination_type: str = None, move_count: int = 0):
        """
        Show the game over widget, replacing the clock widget.
        
        The board remains visible. The game over widget occupies y=144, height=72
        (same as clock) to display the winner, termination reason, and times.
        The analysis widget stays in place (y=216, height=80) showing eval history.
        
        Args:
            result: Game result string (e.g., "1-0", "0-1", "1/2-1/2")
            termination_type: Type of termination (e.g., "CHECKMATE", "STALEMATE", "RESIGN")
            move_count: Number of moves played in the game
        """
        _load_widgets()
        board = _get_board()
        
        try:
            log.info(f"[DisplayManager] Showing game over: result={result}, termination={termination_type}")
            
            # Get final times from clock widget before hiding it
            final_times = None
            if self.clock_widget and self._time_control > 0:
                final_times = self.clock_widget.get_final_times()
                self.clock_widget.stop()
                self.clock_widget.hide()
            elif self.clock_widget:
                # Even in untimed mode, hide the clock (turn indicator)
                self.clock_widget.hide()
            
            # Analysis widget stays in place - game over widget is same size as clock
            
            # Hide brain hint widget if present
            if self.brain_hint_widget:
                self.brain_hint_widget.hide()
            
            if board.display_manager:
                # Create game over widget (y=144, height=72 - same as clock)
                game_over_widget = _GameOverWidget()
                game_over_widget.set_result(result, termination_type, move_count, final_times)
                
                future = board.display_manager.add_widget(game_over_widget)
                if future:
                    try:
                        future.result(timeout=2.0)
                    except Exception:
                        pass
                        
                log.info("[DisplayManager] Game over widget displayed")
        except Exception as e:
            log.error(f"[DisplayManager] Error showing game over: {e}")
    
    def cleanup(self, for_shutdown: bool = False):
        """Clean up resources (analysis engine, widgets) and clear display.
        
        Args:
            for_shutdown: If True, skip creating new widgets (faster shutdown)
        """
        log.info("[DisplayManager] Cleaning up")
        
        board = _get_board()
        
        # Wait for engine init thread if still running (brief wait)
        if self._engine_init_thread is not None and self._engine_init_thread.is_alive():
            try:
                self._engine_init_thread.join(timeout=1.0)
            except Exception:
                pass
        
        # Stop clock widget
        if self.clock_widget:
            try:
                self.clock_widget.stop()
            except Exception as e:
                log.debug(f"[DisplayManager] Error stopping clock widget: {e}")
        
        # Stop analysis widget worker
        if self.analysis_widget:
            try:
                self.analysis_widget._stop_analysis_worker()
            except Exception as e:
                log.debug(f"[DisplayManager] Error stopping analysis worker: {e}")
        
        # Quit analysis engine
        if self.analysis_engine:
            try:
                self.analysis_engine.quit()
            except Exception as e:
                log.debug(f"[DisplayManager] Error quitting analysis engine: {e}")
            self.analysis_engine = None
        
        # Clear widgets - skip creating status bar during shutdown
        if board.display_manager:
            try:
                board.display_manager.clear_widgets(addStatusBar=not for_shutdown)
                log.debug("[DisplayManager] Widgets cleared from display")
            except Exception as e:
                log.debug(f"[DisplayManager] Error clearing widgets: {e}")
