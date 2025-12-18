"""
Game analysis widget displaying evaluation score and history.

Horizontal split layout:
- Left column (44px): Score text, annotation symbol
- Right column (82px): Full-height history graph

Annotation symbols based on score change:
- !! (brilliant): improves by 2+ pawns when losing
- !  (good): improves by 0.5-2 pawns
- !? (interesting): roughly equal trade-off
- ?! (dubious): worsens by 0.5-1 pawn
- ?  (mistake): worsens by 1-2 pawns
- ?? (blunder): worsens by 2+ pawns
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .text import TextWidget, Justify
import os
import queue
import threading
import chess

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class GameAnalysisWidget(Widget):
    """Widget displaying chess game analysis with horizontal split layout.
    
    Layout:
    - Left column (44px wide): Score text (large), annotation symbol
    - Right column (82px wide): Full-height history graph
    
    Uses TextWidget for score and annotation display.
    """
    
    # Default position: below the chess clock widget
    DEFAULT_Y = 216
    DEFAULT_HEIGHT = 80
    
    # Layout constants
    SCORE_COLUMN_WIDTH = 44  # Score text and annotation
    GRAPH_WIDTH = 82  # History graph
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback,
                 bottom_color: str = "black", analysis_engine=None,
                 show_graph: bool = True):
        """Initialize the analysis widget.
        
        Args:
            x: X position on display
            y: Y position on display
            width: Widget width
            height: Widget height
            update_callback: Callback to trigger display updates. Must not be None.
            bottom_color: Color at bottom of board ("white" or "black")
            analysis_engine: chess.engine.SimpleEngine for position analysis
            show_graph: If True, show the history graph
        """
        super().__init__(x, y, width, height, update_callback)
        self.score_value = 0.0
        self.score_text = "0.0"
        self.score_history = []
        self.last_annotation = ""  # Current move annotation (!, ??, etc.)
        self.bottom_color = bottom_color  # "white" or "black" - color at bottom of board
        self._max_history_size = 200
        self.analysis_engine = analysis_engine
        self._show_graph = show_graph
        
        # Track previous score for annotation calculation
        self._previous_score = 0.0
        
        # Create TextWidgets for score and annotation - use parent handler for child updates
        self._score_text_widget = TextWidget(
            0, 4, self.SCORE_COLUMN_WIDTH, 26, self._handle_child_update,
            text="+0.0", font_size=20, 
            justify=Justify.CENTER, transparent=True
        )
        self._annotation_text_widget = TextWidget(
            0, 30, self.SCORE_COLUMN_WIDTH, 24, self._handle_child_update,
            text="", font_size=22,
            justify=Justify.CENTER, transparent=True
        )
        
        # Analysis queue and worker thread
        self._analysis_queue = queue.Queue(maxsize=50)
        self._analysis_worker_thread = None
        self._analysis_worker_stop = threading.Event()
        self._start_analysis_worker()
    
    def _handle_child_update(self, full: bool = False, immediate: bool = False):
        """Handle update requests from child widgets by forwarding to parent callback."""
        return self._update_callback(full, immediate)
    
    def _calculate_annotation(self, current_score: float, previous_score: float) -> str:
        """Calculate annotation symbol based on score change.
        
        Annotations are from the perspective of the side that just moved.
        A positive change means the move helped that side.
        
        Args:
            current_score: Current evaluation (from white's perspective)
            previous_score: Previous evaluation (from white's perspective)
            
        Returns:
            Annotation symbol: !!, !, !?, ?!, ?, ??
        """
        # Calculate change (positive = improvement for side that moved)
        # Note: If it was black's move, they want score to decrease
        # For simplicity, we track absolute change magnitude
        change = current_score - previous_score
        abs_change = abs(change)
        
        # Determine if move was good or bad based on score change direction
        # This needs context of whose move it was, but we can approximate
        # by looking at whether position got more extreme in either direction
        
        # Simplification: use absolute change thresholds
        # Positive change = good for white, negative = good for black
        if abs_change < 0.1:
            return ""  # Neutral, no annotation
        elif abs_change < 0.3:
            return "!?" if change > 0 else "?!"  # Interesting/dubious
        elif abs_change < 0.5:
            return "!" if change > 0 else "?!"
        elif abs_change < 1.0:
            return "!" if change > 0 else "?"
        elif abs_change < 2.0:
            return "!!" if change > 0 else "?"
        else:
            return "!!" if change > 0 else "??"  # Brilliant or blunder
    
    def set_analysis_engine(self, engine) -> None:
        """Set the analysis engine used for position evaluation.
        
        Args:
            engine: chess.engine.SimpleEngine instance or None
        """
        self.analysis_engine = engine
    
    def set_score(self, score_value: float, score_text: str = None) -> None:
        """Set evaluation score."""
        old_score_text = self.score_text
        self.score_value = score_value
        if score_text is None:
            if abs(score_value) > 999:
                self.score_text = ""
            elif abs(score_value) >= 100:
                # Mate in X
                mate_moves = abs(score_value)
                self.score_text = f"Mate {int(mate_moves)}"
            else:
                self.score_text = f"{score_value:5.1f}"
        else:
            self.score_text = score_text
        # Only invalidate cache if score text actually changed
        if self.score_text != old_score_text:
            self.invalidate_cache()
            # Trigger update if scheduler is available
            self.request_update(full=False)
    
    def add_score_to_history(self, score: float) -> None:
        """Add score to history."""
        # History always changes when adding, so always invalidate cache
        # The bar chart width depends on history length
        self.score_history.append(score)
        if len(self.score_history) > self._max_history_size:
            self.score_history.pop(0)
        self.invalidate_cache()
        # Trigger update if scheduler is available
        self.request_update(full=False)
    
    
    def clear_history(self) -> None:
        """Clear score history and pending analysis queue."""
        self.score_history = []
        # Clear the analysis queue to avoid analyzing positions from previous game
        try:
            while not self._analysis_queue.empty():
                try:
                    self._analysis_queue.get_nowait()
                    self._analysis_queue.task_done()
                except queue.Empty:
                    break
        except Exception:
            pass
        self.invalidate_cache()
        # Trigger update if scheduler is available
        self.request_update(full=False)
    
    def reset(self) -> None:
        """Reset widget to initial state (clear history, score, and annotation)."""
        self.clear_history()
        self.score_value = 0.0
        self.score_text = "0.0"
        self.last_annotation = ""
        self._previous_score = 0.0
        self.invalidate_cache()
        self.request_update(full=False)
    
    def set_score_history(self, scores: list) -> None:
        """Set the score history directly (for restoring from database).
        
        Args:
            scores: List of scores in pawns (float values, -12 to +12 range)
        """
        self.score_history = list(scores)
        if len(scores) > 0:
            self.score_value = scores[-1]
            self._previous_score = scores[-1]
            # Format score text
            if abs(self.score_value) > 999:
                self.score_text = "M"
            else:
                self.score_text = f"{self.score_value:+.1f}"
        self.invalidate_cache()
        self.request_update(full=False)
        log.info(f"[GameAnalysisWidget] Restored {len(scores)} scores from history")
    
    def remove_last_score(self) -> None:
        """Remove the last score from history (used for takebacks)."""
        if len(self.score_history) > 0:
            self.score_history.pop()
            self.invalidate_cache()
            # Trigger update if scheduler is available
            self.request_update(full=False)
    
    def _stop_analysis_worker(self):
        """Stop the analysis worker thread."""
        if self._analysis_worker_thread is not None:
            self._analysis_worker_stop.set()
            # Wait for worker to finish current task
            try:
                self._analysis_worker_thread.join(timeout=2.0)
            except Exception:
                pass
            self._analysis_worker_thread = None
    
    def stop(self) -> None:
        """Stop the widget and perform cleanup tasks."""
        self._stop_analysis_worker()
    
    def __del__(self):
        """Cleanup when widget is destroyed."""
        self._stop_analysis_worker()
    
    def get_score_history(self) -> list:
        """Get a copy of the score history."""
        return self.score_history.copy()
    
    def _start_analysis_worker(self):
        """Start the worker thread for processing analysis requests.
        
        Can be called multiple times - only starts if worker is not already running.
        The worker handles the case where the engine is not yet available by waiting.
        """
        # Don't start if already running
        if self._analysis_worker_thread is not None and self._analysis_worker_thread.is_alive():
            return
        
        self._analysis_worker_stop.clear()
        self._analysis_worker_thread = threading.Thread(
            target=self._analysis_worker,
            name="analysis-worker",
            daemon=True
        )
        self._analysis_worker_thread.start()
    
    def _analysis_worker(self):
        """Worker thread that processes analysis requests sequentially.
        
        All queued positions are analyzed in order to ensure the history graph
        is complete. Even if moves come in quickly, each position is analyzed
        so the evaluation history shows the full game progression.
        """
        import logging
        log = logging.getLogger(__name__)
        
        while not self._analysis_worker_stop.is_set():
            try:
                # Get next analysis request (with timeout to allow checking stop event)
                try:
                    request = self._analysis_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                # Wait for engine to be available (in case of async initialization)
                if self.analysis_engine is None:
                    # Put request back and wait
                    try:
                        self._analysis_queue.put_nowait(request)
                    except queue.Full:
                        pass
                    self._analysis_queue.task_done()
                    # Brief sleep to avoid busy loop while waiting for engine
                    import time
                    time.sleep(0.2)
                    continue
                
                # Unpack request
                board_copy, position_fen, is_first_move, time_limit = request
                
                # Analyze every position to ensure complete history graph
                # (don't skip "stale" positions - each move should be in the history)
                try:
                    import chess.engine
                    info = self.analysis_engine.analyse(board_copy, chess.engine.Limit(time=time_limit))
                    
                    # Update widget with analysis result
                    self.update_from_analysis(info, is_first_move)
                    
                except Exception as e:
                    log.warning(f"Error analyzing position: {e}")
                
                self._analysis_queue.task_done()
                
            except Exception as e:
                log.error(f"Error in analysis worker: {e}")
                import traceback
                traceback.print_exc()
    
    def analyze_position(self, board, is_first_move: bool = False, time_limit: float = 0.5) -> None:
        """
        Queue a position for analysis using the analysis engine.
        
        This method queues the analysis request instead of blocking. The analysis
        is performed sequentially in a worker thread, ensuring all positions are
        analyzed and the graph is complete. Stale requests (for positions that
        have changed) are automatically skipped.
        
        If the analysis engine is not yet ready (async initialization in progress),
        positions are still queued and will be processed once the engine and worker
        are available. This ensures a complete history graph even if moves are made
        before the engine finishes starting.
        
        Args:
            board: chess.Board object to analyze
            is_first_move: Whether this is the first move (skip adding to history)
            time_limit: Time limit for analysis in seconds (default 0.5)
        """
        if board is None:
            return
        
        # Get FEN of current position
        try:
            if hasattr(board, 'fen'):
                position_fen = board.fen()
            else:
                # If board doesn't have fen() method, try to create a board from it
                import logging
                log = logging.getLogger(__name__)
                log.warning("Board object does not have fen() method, skipping analysis")
                return
        except Exception as e:
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Could not get FEN from board: {e}, skipping analysis")
            return
        
        # Step 2: Create a copy of the board for analysis (thread-safe)
        # This ensures the board state doesn't change during analysis
        try:
            board_copy = chess.Board(position_fen)
        except Exception:
            import logging
            log = logging.getLogger(__name__)
            log.warning("Could not create board copy for analysis")
            return
        
        # Step 2: Queue analysis request (non-blocking)
        # All positions are queued and analyzed in order to ensure complete history
        try:
            self._analysis_queue.put_nowait((board_copy, position_fen, is_first_move, time_limit))
        except queue.Full:
            import logging
            log = logging.getLogger(__name__)
            log.warning("Analysis queue full, dropping request")
    
    def update_from_analysis(self, analysis_info: dict, is_first_move: bool = False) -> None:
        """
        Update widget from raw chess engine analysis info.
        
        Handles all parsing, formatting, and history management internally.
        Updates all state, then invalidates cache and triggers a single update.
        
        Args:
            analysis_info: Raw analysis info dict from chess engine (must contain "score")
            is_first_move: Whether this is the first move (skip adding to history)
        """
        if "score" not in analysis_info:
            return
        
        # Extract score value from engine analysis info
        score_str = str(analysis_info["score"])
        
        if "Mate" in score_str:
            # Extract mate value
            mate_str = score_str[13:24]
            mate_str = mate_str[1:mate_str.find(")")]
            score_value = float(mate_str)
            score_value = score_value / 100
        else:
            # Extract centipawn value
            cp_str = score_str[11:24]
            cp_str = cp_str[1:cp_str.find(")")]
            score_value = float(cp_str)
            score_value = score_value / 100
        
        # Negate if black is winning (scores are from white's perspective)
        if "BLACK" in score_str:
            score_value = score_value * -1
        
        # Format score text
        score_text = "{:5.1f}".format(score_value)
        if score_value > 999:
            score_text = ""
        
        # Handle mate scores
        if "Mate" in score_str:
            mate_moves = abs(score_value * 100)
            score_text = "Mate in " + "{:2.0f}".format(mate_moves)
            score_value = score_value * 100000
        
        # Clamp score for display (between -12 and 12)
        display_score = score_value
        if display_score > 12:
            display_score = 12
        if display_score < -12:
            display_score = -12
        
        # Calculate annotation based on score change (before updating score)
        if not is_first_move and len(self.score_history) > 0:
            self.last_annotation = self._calculate_annotation(display_score, self._previous_score)
        else:
            self.last_annotation = ""
        
        # Store previous score for next annotation calculation
        self._previous_score = display_score
        
        # Update score state directly (without triggering update)
        self.score_value = display_score
        self.score_text = score_text
        
        # Add to history (skip first move)
        if not is_first_move:
            self.score_history.append(display_score)
            if len(self.score_history) > self._max_history_size:
                self.score_history.pop(0)
        
        # Single cache invalidation and update trigger for all changes
        self.invalidate_cache()
        self.request_update(full=False)
    
    def render(self, sprite: Image.Image) -> None:
        """Render analysis widget with horizontal split layout.
        
        Layout:
        - Left column (44px): Score text, annotation
        - Right column (82px): Full-height history graph (includes all data points)
        """
        log.debug(f"[GameAnalysisWidget] Rendering: y={self.y}, height={self.height}, "
                  f"score_history={len(self.score_history)}, graph={self._show_graph}")
        
        draw = ImageDraw.Draw(sprite)
        
        # Draw background
        self.draw_background_on_sprite(sprite)
        
        # Draw 1px border around widget extent
        draw.rectangle([(0, 0), (self.width - 1, self.height - 1)], fill=None, outline=0)
        
        # Adjust score for display based on bottom color
        # Score is always from white's perspective (positive = white advantage)
        display_score_value = -self.score_value if self.bottom_color == "black" else self.score_value
        
        # Calculate layout: Score text/annotation on left, graph on right
        left_col_width = self.SCORE_COLUMN_WIDTH
        graph_x = left_col_width + 2
        graph_width = self.GRAPH_WIDTH
        graph_right = graph_x + graph_width
        
        # === LEFT COLUMN: Score text, annotation (center-justified) ===
        # Draw vertical separator between score column and graph
        draw.line([(left_col_width, 2), (left_col_width, self.height - 2)], fill=0, width=1)
        
        # Format score text
        if abs(display_score_value) > 999:
            display_score_text = "M"  # Mate
        elif abs(display_score_value) >= 100:
            mate_moves = int(abs(display_score_value))
            display_score_text = f"M{mate_moves}"
        else:
            # Format with sign
            if display_score_value >= 0:
                display_score_text = f"+{display_score_value:.1f}"
            else:
                display_score_text = f"{display_score_value:.1f}"
        
        # Draw score text directly onto sprite (center-justified)
        self._score_text_widget.set_text(display_score_text)
        self._score_text_widget.draw_on(sprite, 0, 4)
        
        # Draw annotation directly onto sprite (center-justified, below score)
        if self.last_annotation:
            self._annotation_text_widget.set_text(self.last_annotation)
            self._annotation_text_widget.draw_on(sprite, 0, 30)
        
        # === RIGHT SECTION: History graph (all data points including last) ===
        # Graph is right-justified: newest values are at the right edge
        history_to_draw = self.score_history
        
        if self._show_graph and len(history_to_draw) > 0:
            graph_top = 4
            graph_bottom = self.height - 4
            graph_height = graph_bottom - graph_top
            
            # Center line
            chart_y = graph_top + graph_height // 2
            draw.line([(graph_x, chart_y), (graph_right, chart_y)], fill=0, width=1)
            
            # Calculate bar width based on history length
            bar_width = graph_width / len(history_to_draw)
            if bar_width > 6:
                bar_width = 6
            
            # Scale factor: map score range (-12 to +12) to half the graph height
            half_height = graph_height // 2
            scale = half_height / 12.0
            
            # Right-justify: calculate starting offset so bars end at graph_right
            total_bars_width = bar_width * len(history_to_draw)
            bar_offset = graph_right - total_bars_width
            
            for score in history_to_draw:
                # Adjust score for display if bottom_color is black
                adjusted_score = -score if self.bottom_color == "black" else score
                # Positive scores (white advantage) go up, use white fill
                # Negative scores (black advantage) go down, use black fill
                color = 255 if adjusted_score >= 0 else 0
                
                # Scale score to pixel offset from center line
                y_offset = adjusted_score * scale
                y_calc = chart_y - y_offset
                y_calc = max(graph_top, min(graph_bottom, y_calc))
                
                y0 = min(chart_y, int(y_calc))
                y1 = max(chart_y, int(y_calc))
                
                draw.rectangle(
                    [(int(bar_offset), y0), (int(bar_offset + bar_width), y1)],
                    fill=color,
                    outline=0
                )
                bar_offset += bar_width
        elif self._show_graph:
            # Still draw the center line even if no history yet
            graph_top = 4
            graph_bottom = self.height - 4
            chart_y = graph_top + (graph_bottom - graph_top) // 2
            draw.line([(graph_x, chart_y), (graph_right, chart_y)], fill=0, width=1)

