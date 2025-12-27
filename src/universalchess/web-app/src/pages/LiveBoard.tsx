import { useState, useCallback } from 'react';
import { ChessBoard } from '../components/ChessBoard';
import { Analysis } from '../components/Analysis';
import { useGameState } from '../hooks/useGameState';
import './LiveBoard.css';

/**
 * Live board page - shows current game with real-time updates.
 */
export function LiveBoard() {
  const { gameState } = useGameState();
  const [displayFen, setDisplayFen] = useState<string | null>(null);

  // Handle position change from Analysis component
  const handlePositionChange = useCallback((fen: string, _moveIndex: number) => {
    setDisplayFen(fen);
  }, []);

  // Current FEN to display (either navigated position or live position)
  const currentFen = displayFen || gameState?.fen || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
  const currentPgn = gameState?.pgn || '';

  return (
    <div className="live-board-page">
      <div className="live-board-main">
        <div className="board-section">
          <ChessBoard
            fen={currentFen}
            boardWidth={500}
          />
        </div>

        <div className="info-section">
          {/* Current Game Info */}
          <div className="game-info-card">
            <h3>Current Game</h3>
            {gameState ? (
              <>
                <div className="players">
                  <span className="player white">{gameState.white || 'White'}</span>
                  <span className="vs">vs</span>
                  <span className="player black">{gameState.black || 'Black'}</span>
                </div>
                {gameState.result && (
                  <div className="result">{gameState.result}</div>
                )}
              </>
            ) : (
              <p className="no-game">No game in progress</p>
            )}
          </div>

          {/* PGN Display */}
          <div className="pgn-card">
            <h3>PGN</h3>
            <textarea
              readOnly
              value={currentPgn}
              placeholder="No moves yet..."
              rows={6}
            />
          </div>
        </div>
      </div>

      {/* Analysis Section */}
      {currentPgn && (
        <div className="analysis-section">
          <Analysis
            pgn={currentPgn}
            mode="live"
            onPositionChange={handlePositionChange}
          />
        </div>
      )}
    </div>
  );
}

