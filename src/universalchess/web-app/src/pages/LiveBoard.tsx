import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { ChessBoard } from '../components/ChessBoard';
import { Analysis } from '../components/Analysis';
import { useGameStore } from '../stores/gameStore';
import './LiveBoard.css';

const SHOW_BEST_MOVE_KEY = 'universalChess.showBestMove';
/** Animation duration for piece movement - matches react-chessboard default */
const ANIMATION_DURATION_MS = 300;

/**
 * Live board page - shows current game with real-time updates.
 * Layout matches original: 2/3 board, 1/3 widgets stacked.
 */
export function LiveBoard() {
  // Use store directly - SSE connection is managed by GameStateProvider
  const gameState = useGameStore((state) => state.gameState);
  const [displayFen, setDisplayFen] = useState<string | null>(null);
  const [bestMove, setBestMove] = useState<{ from: string; to: string } | null>(null);
  const [playedMove, setPlayedMove] = useState<{ from: string; to: string } | null>(null);
  // Delayed arrows that wait for board animation to complete before showing
  const [delayedBestMove, setDelayedBestMove] = useState<{ from: string; to: string } | null>(null);
  const [delayedPlayedMove, setDelayedPlayedMove] = useState<{ from: string; to: string } | null>(null);
  const [pgnExpanded, setPgnExpanded] = useState(false);
  const [isAtLatestMove, setIsAtLatestMove] = useState(true);
  // Track if initial position has been set (to avoid clearing arrows on initial load)
  const hasInitialPositionRef = useRef(false);
  const lastPositionRef = useRef<{ moveIndex: number; totalMoves: number } | null>(null);
  // Timestamp when arrows can next be shown (after animation completes)
  const arrowsAllowedAfterRef = useRef<number>(0);
  // Timer for delayed arrow display
  const arrowDelayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  // Best move visibility for latest position - defaults to hidden, persisted in localStorage
  const [showBestMoveEnabled, setShowBestMoveEnabled] = useState<boolean>(() => {
    const stored = localStorage.getItem(SHOW_BEST_MOVE_KEY);
    return stored === 'true';
  });
  
  // Persist showBestMoveEnabled to localStorage when it changes
  useEffect(() => {
    localStorage.setItem(SHOW_BEST_MOVE_KEY, String(showBestMoveEnabled));
  }, [showBestMoveEnabled]);
  
  const toggleShowBestMove = useCallback(() => {
    setShowBestMoveEnabled((prev) => !prev);
  }, []);
  
  // When enabling show best move, immediately sync delayed arrows with current arrows
  // This ensures arrows appear immediately when toggling on, without waiting for navigation
  // BUT only if we're not within a navigation delay period
  useEffect(() => {
    if (showBestMoveEnabled && bestMove && !delayedBestMove) {
      const now = Date.now();
      const delay = arrowsAllowedAfterRef.current - now;
      // Only set immediately if we're not in a delay period
      if (delay <= 0) {
        setDelayedBestMove(bestMove);
      }
    }
  }, [showBestMoveEnabled, bestMove, delayedBestMove]);

  const handlePositionChange = useCallback((fen: string, moveIndex: number, totalMoves: number) => {
    setDisplayFen(fen);
    setIsAtLatestMove(moveIndex === totalMoves);
    
    // Check if position actually changed (navigation vs initial load)
    const lastPos = lastPositionRef.current;
    const positionActuallyChanged = lastPos && (lastPos.moveIndex !== moveIndex || lastPos.totalMoves !== totalMoves);
    
    // Update position tracking
    lastPositionRef.current = { moveIndex, totalMoves };
    hasInitialPositionRef.current = true;
    
    // Only clear arrows and delay if the position actually changed (navigation)
    // Don't clear on initial load - let the arrows appear naturally from analysis
    if (positionActuallyChanged) {
      // Clear all arrows immediately and set a time-based delay
      // This prevents arrows appearing before piece animation completes
      setDelayedBestMove(null);
      setDelayedPlayedMove(null);
      setBestMove(null);
      setPlayedMove(null);
      // Block arrows until animation completes
      arrowsAllowedAfterRef.current = Date.now() + ANIMATION_DURATION_MS;
      // Clear any pending timer
      if (arrowDelayTimerRef.current) {
        clearTimeout(arrowDelayTimerRef.current);
        arrowDelayTimerRef.current = null;
      }
    }
    // On initial load, don't set any delay - arrows can appear immediately
  }, []);

  const handleBestMoveChange = useCallback((move: { from: string; to: string } | null) => {
    setBestMove(move);
  }, []);

  const handlePlayedMoveChange = useCallback((move: { from: string; to: string } | null) => {
    setPlayedMove(move);
  }, []);
  
  // Sync delayed arrows with source arrows, respecting the time-based delay
  // Key insight: bestMove arrives asynchronously from Stockfish, potentially AFTER
  // the 300ms animation. We use a timestamp to ensure arrows never appear too early.
  useEffect(() => {
    // Clean up any pending timer
    if (arrowDelayTimerRef.current) {
      clearTimeout(arrowDelayTimerRef.current);
      arrowDelayTimerRef.current = null;
    }
    
    const now = Date.now();
    const delay = arrowsAllowedAfterRef.current - now;
    
    if (delay > 0) {
      // Still within the delay period - schedule update for later
      arrowDelayTimerRef.current = setTimeout(() => {
        setDelayedBestMove(bestMove);
        setDelayedPlayedMove(playedMove);
        arrowDelayTimerRef.current = null;
      }, delay);
    } else {
      // Delay has passed - update immediately
      setDelayedBestMove(bestMove);
      setDelayedPlayedMove(playedMove);
    }
    
    return () => {
      if (arrowDelayTimerRef.current) {
        clearTimeout(arrowDelayTimerRef.current);
      }
    };
  }, [bestMove, playedMove]);

  const currentFen = displayFen || gameState?.fen || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
  const currentPgn = gameState?.pgn || '';

  // Game info - using snake_case property names from backend
  const white = gameState?.white || 'White';
  const black = gameState?.black || 'Black';
  const turn = gameState?.turn === 'w' ? 'White' : 'Black';
  const moveNum = gameState?.move_number || 1;
  const result = gameState?.result;
  const gameOver = gameState?.game_over;
  const termination = gameState?.termination;
  
  // Format termination reason for display
  const formatTermination = (term: string | null | undefined): string => {
    if (!term) return '';
    // Convert snake_case or lowercase to Title Case with spaces
    const formatted = term
      .replace(/_/g, ' ')
      .replace(/\./g, ' ')
      .toLowerCase()
      .replace(/\b\w/g, (c) => c.toUpperCase());
    return formatted;
  };
  
  // Blue arrow: pending move (engine waiting) or last move (just executed)
  // Shows "what just happened or needs to happen" on the physical board
  const blueArrowMove = useMemo(() => {
    // Prefer pending move if available (engine/Lichess move waiting to be executed)
    const pendingUci = gameState?.pending_move;
    if (pendingUci && pendingUci.length >= 4) {
      return { from: pendingUci.slice(0, 2), to: pendingUci.slice(2, 4) };
    }
    // Fall back to last move (move that was just executed)
    const lastUci = gameState?.last_move;
    if (lastUci && lastUci.length >= 4) {
      return { from: lastUci.slice(0, 2), to: lastUci.slice(2, 4) };
    }
    return null;
  }, [gameState?.pending_move, gameState?.last_move]);

  return (
    <div className="columns">
      {/* Left column: Board */}
      <div className="column is-8">
        <ChessBoard 
          fen={currentFen} 
          maxBoardWidth={700} 
          showBestMove={isAtLatestMove ? (showBestMoveEnabled ? delayedBestMove : null) : delayedBestMove} 
          showPlayedMove={delayedPlayedMove}
          showPendingMove={isAtLatestMove ? blueArrowMove : null}
        />
      </div>

      {/* Right column: Widgets */}
      <div className="column is-4">
        {/* Current Game Box */}
        <div className="box">
          <h3 className="title is-5 box-title">Current Game</h3>
          {gameState?.fen ? (
            <div className="current-game-info">
              <div className="players-line">
                <strong>{white}</strong>
                <span className="text-muted"> (W)</span>
                {' vs '}
                <strong>{black}</strong>
                <span className="text-muted"> (B)</span>
              </div>
              {gameOver && result ? (
                <div className="game-over-info">
                  <span className="tag is-info">{result}</span>
                  {termination && (
                    <span className="termination-reason">{formatTermination(termination)}</span>
                  )}
                </div>
              ) : (
                <span className="tag is-light">Move {moveNum} - {turn} to play</span>
              )}
            </div>
          ) : (
            <p className="text-muted">Waiting for game...</p>
          )}
        </div>

        {/* Analysis Box */}
        <div className="box" style={{ marginTop: '1rem' }}>
          <h3 className="title is-5 box-title">Analysis</h3>
          <Analysis
            pgn={currentPgn}
            mode="live"
            onPositionChange={handlePositionChange}
            onBestMoveChange={handleBestMoveChange}
            onPlayedMoveChange={handlePlayedMoveChange}
            showBestMoveForLatest={showBestMoveEnabled}
            onToggleShowBestMove={toggleShowBestMove}
          />
        </div>

        {/* Current PGN Box - Collapsible */}
        <div className="box" style={{ marginTop: '1rem' }}>
          <button
            className="pgn-toggle"
            onClick={() => setPgnExpanded(!pgnExpanded)}
            aria-expanded={pgnExpanded}
          >
            <h3 className="title is-5 box-title" style={{ margin: 0 }}>Current PGN</h3>
            <span className="pgn-toggle-icon">{pgnExpanded ? '▼' : '▶'}</span>
          </button>
          {pgnExpanded && (
            <textarea
              id="lastpgn"
              className="textarea"
              placeholder="PGN will appear here during play..."
              rows={8}
              readOnly
              value={currentPgn}
              style={{ marginTop: '0.75rem' }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
