import { useState, useCallback } from 'react';
import { ChessBoard } from '../components/ChessBoard';
import { Analysis } from '../components/Analysis';
import { useGameStore } from '../stores/gameStore';
import './LiveBoard.css';

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
  const [pgnExpanded, setPgnExpanded] = useState(false);

  const handlePositionChange = useCallback((fen: string, _moveIndex: number) => {
    setDisplayFen(fen);
    // Clear arrows when position changes - new analysis will provide them
    setBestMove(null);
    setPlayedMove(null);
  }, []);

  const handleBestMoveChange = useCallback((move: { from: string; to: string } | null) => {
    setBestMove(move);
  }, []);

  const handlePlayedMoveChange = useCallback((move: { from: string; to: string } | null) => {
    setPlayedMove(move);
  }, []);

  const currentFen = displayFen || gameState?.fen || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
  const currentPgn = gameState?.pgn || '';

  // Game info - using snake_case property names from backend
  const white = gameState?.white || 'White';
  const black = gameState?.black || 'Black';
  const turn = gameState?.turn === 'w' ? 'White' : 'Black';
  const moveNum = gameState?.move_number || 1;
  const result = gameState?.result;
  const gameOver = gameState?.game_over;

  return (
    <div className="columns">
      {/* Left column: Board */}
      <div className="column is-8">
        <ChessBoard fen={currentFen} maxBoardWidth={700} showBestMove={bestMove} showPlayedMove={playedMove} />
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
                <span className="tag is-info">{result}</span>
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
