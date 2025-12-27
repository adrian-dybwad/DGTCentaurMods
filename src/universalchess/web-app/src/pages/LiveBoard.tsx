import { useState, useCallback } from 'react';
import { ChessBoard } from '../components/ChessBoard';
import { Analysis } from '../components/Analysis';
import { Card, CardHeader, Textarea } from '../components/ui';
import { useGameState } from '../hooks/useGameState';
import './LiveBoard.css';

/**
 * Live board page - shows current game with real-time updates.
 */
export function LiveBoard() {
  const { gameState } = useGameState();
  const [displayFen, setDisplayFen] = useState<string | null>(null);

  const handlePositionChange = useCallback((fen: string, _moveIndex: number) => {
    setDisplayFen(fen);
  }, []);

  const currentFen = displayFen || gameState?.fen || 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
  const currentPgn = gameState?.pgn || '';

  return (
    <div className="page container--xl">
      <div className="live-layout">
        <section className="live-board">
          <ChessBoard fen={currentFen} boardWidth={500} />
        </section>

        <aside className="live-info">
          <Card>
            <CardHeader title="Current Game" />
            {gameState ? (
              <>
                <div className="player-info">
                  <span className="player player--white">{gameState.white || 'White'}</span>
                  <span className="text-muted">vs</span>
                  <span className="player player--black">{gameState.black || 'Black'}</span>
                </div>
                {gameState.result && (
                  <div className="game-result">{gameState.result}</div>
                )}
              </>
            ) : (
              <p className="text-muted">No game in progress</p>
            )}
          </Card>

          <Card>
            <CardHeader title="PGN" />
            <Textarea
              readOnly
              value={currentPgn}
              placeholder="No moves yet..."
              rows={6}
              block
            />
          </Card>
        </aside>
      </div>

      {currentPgn && (
        <section className="live-analysis mt-6">
          <Analysis
            pgn={currentPgn}
            mode="live"
            onPositionChange={handlePositionChange}
          />
        </section>
      )}
    </div>
  );
}
