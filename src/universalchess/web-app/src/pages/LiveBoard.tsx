import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ChessBoard } from '../components/ChessBoard';
import { Analysis } from '../components/Analysis';
import { useGameState } from '../hooks/useGameState';
import './LiveBoard.css';

/**
 * Live board page - shows current game with real-time updates.
 * Layout matches original: 2/3 board, 1/3 widgets stacked.
 */
export function LiveBoard() {
  const { gameState } = useGameState();
  const [displayFen, setDisplayFen] = useState<string | null>(null);

  const handlePositionChange = useCallback((fen: string, _moveIndex: number) => {
    setDisplayFen(fen);
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
        <ChessBoard fen={currentFen} boardWidth={500} />
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
          />
        </div>

        {/* Current PGN Box */}
        <div className="box" style={{ marginTop: '1rem' }}>
          <h3 className="title is-5 box-title">Current PGN</h3>
          <textarea
            id="lastpgn"
            className="textarea"
            placeholder="PGN will appear here during play..."
            rows={8}
            readOnly
            value={currentPgn}
          />
        </div>

        {/* View All Games Button */}
        <Link to="/games" className="button is-primary is-small" style={{ marginTop: '1rem' }}>
          View All Games
        </Link>
      </div>
    </div>
  );
}
