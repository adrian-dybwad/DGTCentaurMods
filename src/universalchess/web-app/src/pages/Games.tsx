import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import type { GameRecord } from '../types/game';
import './Games.css';

/**
 * Games history page.
 */
export function Games() {
  const [games, setGames] = useState<GameRecord[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [expandedPgn, setExpandedPgn] = useState<Record<number, string>>({});

  const fetchGames = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`/getgames/${page}`);
      const data = await response.json();
      const gameList = Object.values(data) as GameRecord[];
      setGames(gameList);
    } catch (e) {
      console.error('Failed to fetch games:', e);
      setGames([]);
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    fetchGames();
  }, [fetchGames]);

  const togglePgn = async (gameId: number) => {
    if (expandedPgn[gameId]) {
      setExpandedPgn((prev) => {
        const next = { ...prev };
        delete next[gameId];
        return next;
      });
      return;
    }

    try {
      const response = await fetch(`/getpgn/${gameId}`);
      const pgn = await response.text();
      setExpandedPgn((prev) => ({ ...prev, [gameId]: pgn }));
    } catch (e) {
      console.error('Failed to fetch PGN:', e);
    }
  };

  const deleteGame = async (gameId: number) => {
    if (!confirm('Delete this game? This cannot be undone.')) return;
    try {
      await fetch(`/deletegame/${gameId}`);
      fetchGames();
    } catch (e) {
      console.error('Failed to delete game:', e);
    }
  };

  return (
    <div className="games-page">
      <div className="page-header">
        <h1>Game History</h1>
        <div className="pagination">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
            ◀ Previous
          </button>
          <span>Page {page}</span>
          <button onClick={() => setPage((p) => p + 1)} disabled={games.length === 0}>
            Next ▶
          </button>
        </div>
      </div>

      {loading ? (
        <div className="loading">Loading games...</div>
      ) : games.length === 0 ? (
        <div className="empty">No games found</div>
      ) : (
        <div className="games-list">
          {games.map((game) => (
            <div key={game.id} className="game-card">
              <div className="game-header">
                <div className="players">
                  <strong>{game.white || 'Player'}</strong>
                  <span className="color-indicator">(W)</span>
                  <span className="vs">vs</span>
                  <strong>{game.black || 'Player'}</strong>
                  <span className="color-indicator">(B)</span>
                </div>
                {game.result && <span className="result">{game.result}</span>}
              </div>

              <div className="game-meta">
                {game.created_at && (
                  <span>{new Date(game.created_at).toLocaleDateString()}</span>
                )}
                {game.source && <span>{game.source}</span>}
              </div>

              {expandedPgn[game.id] && (
                <pre className="pgn-display">{expandedPgn[game.id]}</pre>
              )}

              <div className="game-actions">
                <button onClick={() => togglePgn(game.id)}>
                  {expandedPgn[game.id] ? 'Hide PGN' : 'Show PGN'}
                </button>
                <Link to={`/analyze/${game.id}`} className="btn-primary">
                  Analyze
                </Link>
                <button className="btn-danger" onClick={() => deleteGame(game.id)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

