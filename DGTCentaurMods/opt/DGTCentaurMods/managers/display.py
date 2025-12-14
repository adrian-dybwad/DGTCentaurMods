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
                 show_clock: bool = True, show_score_bar: bool = True,
                 show_graph: bool = True):
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
            show_score_bar: If True, show the score bar in analysis widget
            show_graph: If True, show the history graph in analysis widget
        """
        _load_widgets()
        
        self._flip_board = flip_board
        self._show_analysis = show_analysis
        self._on_exit = on_exit
        self._hand_brain_mode = hand_brain_mode
        self._initial_fen = initial_fen or STARTING_FEN
        self._time_control = time_control  # Minutes per player (0 = disabled)
        self._show_board = show_board
        self._show_clock = show_clock
        self._show_score_bar = show_score_bar
        self._show_graph = show_graph
        
        # Widgets
        self.chess_board_widget = None
        self.clock_widget = None
        self.analysis_widget = None
        self.analysis_engine = None
        self.brain_hint_widget = None
        self.alert_widget = None
        
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
    
    def _init_widgets(self):
        """Create and add widgets to the display manager.
        
        Layout:
        - Status bar: y=0, height=16
        - Chess board: y=16, height=128
        - Clock widget: y=144, height=72 (prominent turn/time display)
        - Analysis widget: y=216, height=80 (eval bar and history)
        """
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
        
        # Add widgets without blocking - display will catch up
        # This allows game logic to start while display updates queue
        if self._show_board:
            board.display_manager.add_widget(self.chess_board_widget)
            log.info("[DisplayManager] Chess board widget initialized")
        else:
            log.info("[DisplayManager] Chess board widget disabled")
        
        # Calculate dynamic layout based on which widgets are shown
        # Available space: y=144 to y=296 (152 pixels total)
        # Layout depends on what's enabled:
        # - Clock needs more space if timed mode, less if just turn indicator
        # - Analysis needs more space if score bar enabled, less if just graph
        
        # Determine analysis widget height based on what it shows
        if self._show_analysis:
            if self._show_score_bar and self._show_graph:
                # Full analysis: score bar (28px) + graph area (50px) + padding
                analysis_height = 80
            elif self._show_score_bar:
                # Score bar only
                analysis_height = 40
            elif self._show_graph:
                # Graph only
                analysis_height = 54
            else:
                # Nothing visible but widget exists
                analysis_height = 0
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
        
        if self._show_clock:
            board.display_manager.add_widget(self.clock_widget)
            log.info(f"[DisplayManager] Clock widget initialized (y={clock_y}, height={clock_height}, time_control={self._time_control} min)")
        else:
            log.info("[DisplayManager] Clock widget disabled")
        
        # Create analysis widget below clock
        # Pass display settings for score bar and graph
        bottom_color = "black" if self.chess_board_widget.flip else "white"
        self.analysis_widget = _GameAnalysisWidget(
            x=0, y=analysis_y, width=128, height=analysis_height if analysis_height > 0 else 80,
            bottom_color=bottom_color,
            analysis_engine=self.analysis_engine,
            show_score_bar=self._show_score_bar,
            show_graph=self._show_graph
        )
        
        if not self._show_analysis:
            self.analysis_widget.hide()
        
        board.display_manager.add_widget(self.analysis_widget)
        log.info(f"[DisplayManager] Analysis widget initialized (visible={self._show_analysis}, score_bar={self._show_score_bar}, graph={self._show_graph})")
        
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
    
    def show_queen_threat_alert(self, is_black_queen_threatened: bool, 
                                 attacker_square: int, queen_square: int) -> None:
        """Show YOUR QUEEN alert and flash LEDs from attacker to queen.
        
        Args:
            is_black_queen_threatened: True if black queen is threatened, False if white
            attacker_square: Square index (0-63) of the attacking piece
            queen_square: Square index (0-63) of the threatened queen
        """
        if self.alert_widget:
            self.alert_widget.show_queen_threat(is_black_queen_threatened, attacker_square, queen_square)
    
    def hide_alert(self) -> None:
        """Hide the alert widget."""
        if self.alert_widget:
            self.alert_widget.hide()
    
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
