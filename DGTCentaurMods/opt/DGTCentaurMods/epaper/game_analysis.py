"""
Game analysis widget displaying evaluation score, history, and turn indicator.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os
import queue
import threading
import chess


class GameAnalysisWidget(Widget):
    """Widget displaying chess game analysis information."""
    
    def __init__(self, x: int, y: int, width: int = 128, height: int = 80, bottom_color: str = "black", analysis_engine=None):
        super().__init__(x, y, width, height)
        self.score_value = 0.0
        self.score_text = "0.0"
        self.score_history = []
        self.current_turn = "white"  # "white" or "black"
        self.bottom_color = bottom_color  # "white" or "black" - color at bottom of board
        self._font = self._load_font()
        self._max_history_size = 200
        self.analysis_engine = analysis_engine  # chess.engine.SimpleEngine for analysis
        
        # Analysis queue and worker thread
        # Queue holds analysis requests until worker processes them
        # All positions are analyzed in order to ensure complete history graph
        self._analysis_queue = queue.Queue(maxsize=50)
        self._analysis_worker_thread = None
        self._analysis_worker_stop = threading.Event()
        self._start_analysis_worker()
    
    def _load_font(self):
        """Load font with fallbacks."""
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, 12)
                except:
                    pass
        return ImageFont.load_default()
    
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
            self._last_rendered = None
            # Trigger update if scheduler is available
            self.request_update(full=False)
    
    def add_score_to_history(self, score: float) -> None:
        """Add score to history."""
        # History always changes when adding, so always invalidate cache
        # The bar chart width depends on history length
        self.score_history.append(score)
        if len(self.score_history) > self._max_history_size:
            self.score_history.pop(0)
        self._last_rendered = None
        # Trigger update if scheduler is available
        self.request_update(full=False)
    
    def set_turn(self, turn: str) -> None:
        """Set current turn ('white' or 'black')."""
        if self.current_turn != turn:
            self.current_turn = turn
            self._last_rendered = None
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
        self._last_rendered = None
        # Trigger update if scheduler is available
        self.request_update(full=False)
    
    def reset(self) -> None:
        """Reset widget to initial state (clear history and reset score)."""
        self.clear_history()
        self.set_score(0.0, "0.0")
    
    def remove_last_score(self) -> None:
        """Remove the last score from history (used for takebacks)."""
        if len(self.score_history) > 0:
            self.score_history.pop()
            self._last_rendered = None
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
                board_copy, position_fen, current_turn, is_first_move, time_limit = request
                
                # Analyze every position to ensure complete history graph
                # (don't skip "stale" positions - each move should be in the history)
                try:
                    import chess.engine
                    info = self.analysis_engine.analyse(board_copy, chess.engine.Limit(time=time_limit))
                    
                    # Update widget with analysis result
                    self.update_from_analysis(info, current_turn, is_first_move)
                    
                except Exception as e:
                    log.warning(f"Error analyzing position: {e}")
                
                self._analysis_queue.task_done()
                
            except Exception as e:
                log.error(f"Error in analysis worker: {e}")
                import traceback
                traceback.print_exc()
    
    def analyze_position(self, board, current_turn: str, is_first_move: bool = False, time_limit: float = 0.5) -> None:
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
        
        Sequence:
        1. Update turn indicator immediately (fast operation)
        2. Queue analysis request (non-blocking)
        3. Worker thread processes request and updates score/history
        
        Args:
            board: chess.Board object to analyze
            current_turn: Current turn as "white" or "black"
            is_first_move: Whether this is the first move (skip adding to history)
            time_limit: Time limit for analysis in seconds (default 0.5)
        """
        if board is None:
            return
        
        # Step 1: Update turn indicator immediately (fast operation)
        # This allows the turn circle to update before the slow analysis completes
        self.set_turn(current_turn)
        
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
        
        # Step 3: Queue analysis request (non-blocking)
        # All positions are queued and analyzed in order to ensure complete history
        try:
            self._analysis_queue.put_nowait((board_copy, position_fen, current_turn, is_first_move, time_limit))
        except queue.Full:
            import logging
            log = logging.getLogger(__name__)
            log.warning("Analysis queue full, dropping request")
    
    def update_from_analysis(self, analysis_info: dict, current_turn: str, is_first_move: bool = False) -> None:
        """
        Update widget from raw chess engine analysis info.
        
        Handles all parsing, formatting, and history management internally.
        Updates all state, then invalidates cache and triggers a single update.
        
        Args:
            analysis_info: Raw analysis info dict from chess engine (must contain "score")
            current_turn: Current turn as "white" or "black" (already updated in analyze_position)
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
        
        # Update score state directly (without triggering update)
        self.score_value = display_score
        self.score_text = score_text
        
        # Add to history (skip first move)
        if not is_first_move:
            self.score_history.append(display_score)
            if len(self.score_history) > self._max_history_size:
                self.score_history.pop(0)
        
        # Single cache invalidation and update trigger for all changes
        self._last_rendered = None
        self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render analysis widget."""
        # Return cached image if available
        if self._last_rendered is not None:
            return self._last_rendered

        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Adjust score for display based on bottom color
        # Score is always from white's perspective (positive = white advantage)
        # If bottom is black (board is flipped), we need to flip (negative = black losing, positive = black winning)
        # If bottom is white (board not flipped), no adjustment needed (positive = white winning, negative = white losing)
        # This ensures negative always represents bottom color's disadvantage
        display_score_value = -self.score_value if self.bottom_color == "black" else self.score_value
        
        # Format score text for display (adjust if needed)
        # Regenerate text from adjusted display_score_value to ensure consistency
        if self.bottom_color == "black":
            # Regenerate text from adjusted score to match the bar display
            if abs(display_score_value) > 999:
                display_score_text = ""
            elif abs(display_score_value) >= 100:
                mate_moves = abs(display_score_value)
                display_score_text = f"Mate {int(mate_moves)}"
            else:
                display_score_text = f"{display_score_value:5.1f}"
        else:
            # Use original text (no adjustment needed when bottom is white - board not flipped)
            display_score_text = self.score_text
        
        # Draw score text
        if display_score_text:
            draw.text((50, 12), display_score_text, font=self._font, fill=0)
        
        # Draw score indicator box
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline=0)
        
        # Calculate indicator position (clamp score between -12 and 12)
        score_display = display_score_value
        if score_display > 12:
            score_display = 12
        if score_display < -12:
            score_display = -12
        
        # Draw indicator bar
        offset = (128 / 25) * (score_display + 12)
        if offset < 128:
            draw.rectangle([(int(offset), 1), (127, 11)], fill=0, outline=0)
        
        # Draw score history bar chart
        if len(self.score_history) > 0:
            chart_y = 50
            draw.line([(0, chart_y), (128, chart_y)], fill=0, width=1)
            
            bar_width = 128 / len(self.score_history)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.score_history:
                # Adjust score for display if bottom_color is black (board is flipped)
                adjusted_score = -score if self.bottom_color == "black" else score
                color = 255 if adjusted_score >= 0 else 0
                y_calc = chart_y - (adjusted_score * 2)
                y0 = min(chart_y, y_calc)
                y1 = max(chart_y, y_calc)
                draw.rectangle(
                    [(int(bar_offset), int(y0)), (int(bar_offset + bar_width), int(y1))],
                    fill=color,
                    outline=0
                )
                bar_offset += bar_width
        
        # Draw turn indicator showing which color is at the bottom of the board
        # When board is flipped (bottom_color == "black"), we need to invert the turn
        # to show which color is physically at the bottom
        if self.bottom_color == "black":
            # Board is flipped: invert the turn to show bottom color
            bottom_turn = "black" if self.current_turn == "white" else "white"
        else:
            # Board not flipped: turn directly indicates bottom color
            bottom_turn = self.current_turn
        
        # Draw circle: white circle (fill=255) for white at bottom, black circle (fill=0) for black at bottom
        if bottom_turn == "white":
            draw.ellipse((119, 14, 126, 21), fill=255, outline=0)
        else:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        
        # Cache the rendered image
        self._last_rendered = img
        return img

