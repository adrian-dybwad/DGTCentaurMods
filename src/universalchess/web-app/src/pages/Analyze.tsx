import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { ChessBoard } from '../components/ChessBoard';
import { Analysis } from '../components/Analysis';
import './Analyze.css';

/**
 * Game analysis page for historical games.
 */
export function Analyze() {
  const { gameId } = useParams<{ gameId: string }>();
  const [pgn, setPgn] = useState('');
  const [currentFen, setCurrentFen] = useState('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!gameId) return;

    setLoading(true);
    setError(null);

    fetch(`/getpgn/${gameId}`)
      .then((res) => {
        if (!res.ok) throw new Error('Game not found');
        return res.text();
      })
      .then((data) => {
        setPgn(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [gameId]);

  const handlePositionChange = useCallback((fen: string, _moveIndex: number) => {
    setCurrentFen(fen);
  }, []);

  if (loading) {
    return (
      <div className="analyze-page">
        <div className="loading">Loading game...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="analyze-page">
        <div className="error">{error}</div>
      </div>
    );
  }

  return (
    <div className="analyze-page">
      <h1>Game Analysis</h1>

      <div className="analyze-layout">
        <div className="board-section">
          <ChessBoard fen={currentFen} boardWidth={450} />
        </div>

        <div className="analysis-section">
          <Analysis
            pgn={pgn}
            mode="static"
            onPositionChange={handlePositionChange}
          />
        </div>
      </div>

      <div className="pgn-section">
        <h3>PGN</h3>
        <pre>{pgn}</pre>
      </div>
    </div>
  );
}

