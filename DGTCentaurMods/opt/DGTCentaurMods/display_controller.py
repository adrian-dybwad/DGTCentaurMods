"""
Display controller for managing game-related UI widgets.

This module provides a centralized controller for all game display widgets,
handling widget lifecycle, menu presentation, and display state management.
It separates UI concerns from game logic (GameManager) and protocol handling (GameHandler).

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
_IconMenuWidget = None
_IconMenuEntry = None
_SplashScreen = None


def _get_board():
    """Lazily import and return the board module."""
    global _board_module
    if _board_module is None:
        from DGTCentaurMods.board import board
        _board_module = board
    return _board_module


def _load_widgets():
    """Lazily load widget classes."""
    global _widgets_loaded, _ChessBoardWidget, _GameAnalysisWidget
    global _IconMenuWidget, _IconMenuEntry, _SplashScreen
    
    if _widgets_loaded:
        return
    
    from DGTCentaurMods.epaper import (
        ChessBoardWidget, GameAnalysisWidget, 
        IconMenuWidget, IconMenuEntry, SplashScreen
    )
    _ChessBoardWidget = ChessBoardWidget
    _GameAnalysisWidget = GameAnalysisWidget
    _IconMenuWidget = IconMenuWidget
    _IconMenuEntry = IconMenuEntry
    _SplashScreen = SplashScreen
    _widgets_loaded = True


# Starting position FEN
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class DisplayController:
    """Controller for game display widgets.
    
    Manages the lifecycle of game-related widgets and handles UI interactions
    like menus. Provides a clean interface for game logic to update the display
    without knowing about widget implementation details.
    
    Attributes:
        chess_board_widget: The chess board display widget
        analysis_widget: The game analysis/evaluation widget
        analysis_engine: UCI engine for position analysis
    """
    
    def __init__(self, flip_board: bool = False, show_analysis: bool = True,
                 analysis_engine_path: str = None, on_exit: callable = None):
        """Initialize the display controller.
        
        Args:
            flip_board: If True, display board from black's perspective
            show_analysis: If True, show analysis widget (default visible)
            analysis_engine_path: Path to UCI engine for analysis (e.g., ct800)
            on_exit: Callback function() when user requests exit via back menu
        """
        _load_widgets()
        
        self._flip_board = flip_board
        self._show_analysis = show_analysis
        self._on_exit = on_exit
        
        # Widgets
        self.chess_board_widget = None
        self.analysis_widget = None
        self.analysis_engine = None
        
        # Menu state
        self._menu_active = False
        self._current_menu = None
        self._menu_result_callback = None
        
        # Key callback for routing during menu
        self._original_key_callback = None
        self._key_callback = None
        
        # Initialize analysis engine
        if analysis_engine_path:
            self._init_analysis_engine(analysis_engine_path)
        
        # Initialize widgets
        self._init_widgets()
    
    def _init_analysis_engine(self, engine_path: str):
        """Initialize the UCI analysis engine.
        
        Args:
            engine_path: Path to the UCI engine executable
        """
        try:
            resolved_path = str(pathlib.Path(engine_path).resolve())
            self.analysis_engine = chess.engine.SimpleEngine.popen_uci(resolved_path, timeout=None)
            log.info(f"[DisplayController] Analysis engine initialized: {resolved_path}")
        except Exception as e:
            log.warning(f"[DisplayController] Could not initialize analysis engine: {e}")
            self.analysis_engine = None
    
    def _init_widgets(self):
        """Create and add widgets to the display manager."""
        board = _get_board()
        
        if not board.display_manager:
            log.error("[DisplayController] No display manager available")
            return
        
        # Clear any existing widgets
        board.display_manager.clear_widgets()
        
        # Create chess board widget at y=16 (below status bar)
        self.chess_board_widget = _ChessBoardWidget(0, 16, STARTING_FEN)
        if self._flip_board:
            self.chess_board_widget.set_flip(True)
        
        future = board.display_manager.add_widget(self.chess_board_widget)
        if future:
            try:
                future.result(timeout=5.0)
            except Exception as e:
                log.warning(f"[DisplayController] Error displaying chess board: {e}")
        log.info("[DisplayController] Chess board widget initialized")
        
        # Create analysis widget at bottom (y=144, which is 16+128)
        bottom_color = "black" if self.chess_board_widget.flip else "white"
        self.analysis_widget = _GameAnalysisWidget(
            0, 144, 128, 80,
            bottom_color=bottom_color,
            analysis_engine=self.analysis_engine
        )
        
        if not self._show_analysis:
            self.analysis_widget.hide()
        
        future = board.display_manager.add_widget(self.analysis_widget)
        if future:
            try:
                future.result(timeout=5.0)
            except Exception as e:
                log.warning(f"[DisplayController] Error displaying analysis widget: {e}")
        log.info(f"[DisplayController] Analysis widget initialized (visible={self._show_analysis})")
    
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
                log.error(f"[DisplayController] Error updating position: {e}")
    
    def analyze_position(self, board_obj: chess.Board, current_turn: str,
                        is_first_move: bool = False, time_limit: float = 0.3):
        """Trigger position analysis.
        
        Analysis runs even when widget is hidden to collect history.
        
        Args:
            board_obj: chess.Board object to analyze
            current_turn: "white" or "black"
            is_first_move: If True, don't add to history
            time_limit: Analysis time limit in seconds
        """
        if self.analysis_widget:
            try:
                self.analysis_widget.analyze_position(
                    board_obj, current_turn, is_first_move, time_limit
                )
            except Exception as e:
                log.debug(f"[DisplayController] Error analyzing position: {e}")
    
    def toggle_analysis(self):
        """Toggle analysis widget visibility."""
        if self.analysis_widget:
            if self.analysis_widget.visible:
                log.info("[DisplayController] Hiding analysis widget")
                self.analysis_widget.hide()
            else:
                log.info("[DisplayController] Showing analysis widget")
                self.analysis_widget.show()
    
    def reset_analysis(self):
        """Reset analysis widget (clear history, reset score)."""
        if self.analysis_widget:
            try:
                log.info("[DisplayController] Resetting analysis widget")
                self.analysis_widget.reset()
            except Exception as e:
                log.warning(f"[DisplayController] Error resetting analysis: {e}")
    
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
        
        log.info(f"[DisplayController] Promotion selected: {selected_piece[0]}")
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
        
        log.info(f"[DisplayController] Showing back menu (two_player={is_two_player})")
        
        if is_two_player:
            # In 2-player mode, show separate resign options for each side
            entries = [
                _IconMenuEntry(key="resign_white", label="White\nResigns", icon_name="resign"),
                _IconMenuEntry(key="resign_black", label="Black\nResigns", icon_name="resign"),
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
                    log.debug(f"[DisplayController] Error displaying menu: {e}")
        
        # Activate menu
        back_menu.activate()
        
        # Start thread to wait for result
        def wait_for_result():
            try:
                back_menu._selection_event.wait()
                result = back_menu._selection_result or "BACK"
                
                log.info(f"[DisplayController] Back menu result: {result}")
                
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
                log.error(f"[DisplayController] Error in back menu: {e}")
                import traceback
                traceback.print_exc()
                self._menu_active = False
                self._current_menu = None
                if self._menu_result_callback:
                    self._menu_result_callback("cancel")
        
        wait_thread = threading.Thread(target=wait_for_result, daemon=True)
        wait_thread.start()
    
    def show_kings_center_menu(self, on_result: callable, is_two_player: bool = False):
        """Show confirmation menu when kings are placed in center (resign/draw gesture).
        
        Non-blocking - calls on_result when user makes a selection.
        
        Args:
            on_result: Callback function(result: str) with result:
                      'resign', 'resign_white', 'resign_black', 'draw', or 'cancel'
            is_two_player: If True, show separate resign options for white and black
        """
        board = _get_board()
        
        log.info(f"[DisplayController] Showing kings-in-center menu (two_player={is_two_player})")
        
        if is_two_player:
            entries = [
                _IconMenuEntry(key="resign_white", label="White\nResigns", icon_name="resign"),
                _IconMenuEntry(key="resign_black", label="Black\nResigns", icon_name="resign"),
                _IconMenuEntry(key="draw", label="Draw", icon_name="draw"),
                _IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel"),
            ]
        else:
            entries = [
                _IconMenuEntry(key="resign", label="Resign", icon_name="resign"),
                _IconMenuEntry(key="draw", label="Draw", icon_name="draw"),
                _IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel"),
            ]
        
        kings_menu = _IconMenuWidget(
            x=0, y=0, width=128, height=296,
            entries=entries,
            selected_index=len(entries) - 1
        )
        
        self._menu_result_callback = on_result
        self._current_menu = kings_menu
        self._menu_active = True
        
        if board.display_manager:
            board.display_manager.clear_widgets(addStatusBar=False)
            future = board.display_manager.add_widget(kings_menu)
            if future:
                try:
                    future.result(timeout=2.0)
                except Exception as e:
                    log.debug(f"[DisplayController] Error displaying menu: {e}")
        
        board.beep(board.SOUND_GENERAL)
        kings_menu.activate()
        
        def wait_for_result():
            try:
                kings_menu._selection_event.wait()
                result = kings_menu._selection_result or "BACK"
                
                log.info(f"[DisplayController] Kings-in-center menu result: {result}")
                
                self._menu_active = False
                kings_menu.deactivate()
                self._current_menu = None
                
                if result == "BACK":
                    result = "cancel"
                elif result == "SHUTDOWN":
                    result = "cancel"
                
                if result == "cancel":
                    self._restore_game_display()
                
                if self._menu_result_callback:
                    self._menu_result_callback(result)
                    
            except Exception as e:
                log.error(f"[DisplayController] Error in kings-in-center menu: {e}")
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
                
                # Re-add analysis widget
                if self.analysis_widget:
                    future = board.display_manager.add_widget(self.analysis_widget)
                    if future:
                        try:
                            future.result(timeout=2.0)
                        except Exception:
                            pass
                            
                log.debug("[DisplayController] Game display restored")
        except Exception as e:
            log.error(f"[DisplayController] Error restoring display: {e}")
    
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
            log.debug(f"[DisplayController] Error showing splash: {e}")
    
    def cleanup(self):
        """Clean up resources (analysis engine, widgets)."""
        log.info("[DisplayController] Cleaning up")
        
        # Stop analysis widget worker
        if self.analysis_widget:
            try:
                self.analysis_widget._stop_analysis_worker()
            except Exception as e:
                log.debug(f"[DisplayController] Error stopping analysis worker: {e}")
        
        # Quit analysis engine
        if self.analysis_engine:
            try:
                self.analysis_engine.quit()
            except Exception as e:
                log.debug(f"[DisplayController] Error quitting analysis engine: {e}")
            self.analysis_engine = None
